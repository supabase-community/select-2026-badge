"""A fleet glyph effect as a temporary Nametag skin, never persisted.

The network runtime owns command validation, duration, phase, acknowledgements,
case lights and panel brightness.  This module only observes its active player
and asks the already-open Nametag renderer for pixels while that player exists.
Everything needed to draw is injected so importing this file cannot pull the
Glyph viewer or another app into Nametag's launch path.
"""


NONE = 0
PAINTED = 1
RESTORED = 2


class _ShowPack:
    """Show streams over Nametag's existing masks and vivid colour table.

    The generated pack contains only the library-derived GPD members. Duplicating
    the normal pack's 25,500-byte mask banks and 30,720-byte treatment tables
    would spend flash for byte-identical resources, while this adapter lets
    `glyphskin.skin` keep using its ordinary `stream`/`masks`/`lut` protocol
    unchanged.
    """

    def __init__(self, streams, resources):
        self.streams = streams
        self.resources = resources

    def stream(self, technique):
        return self.streams.stream(technique)

    def masks(self, cell_w, cell_h):
        return self.resources.masks(cell_w, cell_h)

    def lut(self, treatment):
        return self.resources.lut(treatment)


class GlyphShow:
    """Synchronise one temporary backdrop with a service's active-effect slot."""

    def __init__(self, network, view, state, poster_module, screen, clear_pen,
                 restore, ticks_diff, show_pack_path, emit=print):
        self.network = network
        self.view = view
        self.state = state
        self.nametag = poster_module
        self.screen = screen
        self.clear_pen = clear_pen
        self.restore = restore
        self.ticks_diff = ticks_diff
        self.show_pack_path = show_pack_path
        self.emit = emit
        self.player = None
        self.plan = None
        self._base_pack = None
        self._show_pack = None
        self._packs_open = False

    @property
    def active(self):
        """Whether Nametag has observed a live glyph player, pixels or not."""
        # Include a service slot seated before the first Nametag update; the
        # labelled press route is checked before `step()` observes that slot.
        return self.player is not None or self._effect() is not None

    def _effect(self):
        """The live glyph player, or None. Total by the badge reset rule.

        `_effect` is the frozen active-effect slot. The guarded shape mirrors
        `note_panel_level`: the shipping configuration has no injected service,
        an older service may have no slot, and an accessor that raises must
        leave Nametag being Nametag rather than reach `fatal_error`.
        """
        if self.network is None:
            return None
        try:
            player = getattr(self.network, "_effect", None)
            if (player is None or getattr(player, "kind", None) != "glyph"
                    or bool(getattr(player, "done", False))):
                return None
            return player
        except Exception:  # an optional seam cannot reset Nametag
            return None

    @staticmethod
    def _deck_for(player):
        """Map the number through its defining library, never a copied table.

        Effect ids are append-only protocol positions in `effect_library`.
        Copying their deck names here would let a tuning make the lights play
        one rhythm while the panel silently showed another. The import remains
        lazy for `/system/lib`'s half-refresh rule; every failure means lights
        only.
        """
        try:
            import effect_library

            row = effect_library.describe("glyph", player.effect_id)
            name = row.get("name") if isinstance(row, dict) else None
            if not isinstance(name, str) or not name:
                return ""
            return "glyph." + name
        except Exception:
            return ""

    def _elapsed(self, player, now):
        """Pixel clock including the runtime's execute_at skew correction.

        A boot-relative clock alone starts badges in the same second but at
        unrelated deck phases. The runtime already recorded its local start and
        seated the player at `skew_ms`; following both values keeps pixels on
        the same fleet clock as the light and panel channels.
        """
        try:
            started = getattr(self.network, "_effect_started", now)
            elapsed = self.ticks_diff(now, started)
            if elapsed < 0:
                elapsed = 0
            skew = int(getattr(player, "skew_ms", 0))
            return elapsed + (skew if skew > 0 else 0)
        except Exception:
            return 0

    def _forget_failed_deck(self, deck):
        """Make Nametag's total fallback eligible for the one real retry.

        `Nametag.background` records `_backdrop_id` before opening a glyph stream
        and turns missing bytes into a wash. Without clearing that private cache
        key, retry two would return the wash without touching flash. No wearer
        or persisted state changes, and a successful retry fills the backdrop
        before the id is trusted again.
        """
        try:
            if getattr(self.view, "_backdrop_id", None) == deck:
                self.view._backdrop_id = ""
                self.view.artist = None
        except Exception:
            pass
        if self._show_pack is None:
            # A total `open_pack` reports allocation failure as no pack. Clear
            # its attempted-open latch too, or the promised retry would merely
            # read our own cached None instead of touching the directory again.
            self._base_pack = None
            self._packs_open = False

    def _open_packs(self):
        """Open stream bytes beside the renderer resources they reuse.

        `glyphskin`, the normal wearer-skin player, is the only player imported.
        The show-only pack exists because two valid effect decks were cut from
        the wearer picker; it restores protocol completeness without restoring
        either catalogue row. Both opens are total, and no retained show object
        survives `_restore_packs`.
        """
        if self._packs_open:
            return self._show_pack is not None
        self._packs_open = True
        try:
            import glyphskin

            streams = glyphskin.open_pack(self.show_pack_path)
            self._base_pack = self.view.pack
            if streams is None or self._base_pack is None:
                return False
            self._show_pack = _ShowPack(streams, self._base_pack)
            return True
        except Exception:
            return False

    def _restore_packs(self):
        """Give Nametag its wearer pack back and forget every show reference."""
        try:
            if self._packs_open:
                self.view.pack = self._base_pack
            # The backdrop pixels may name a show-only id the wearer catalogue
            # cannot classify. Force the ordinary wearer call to rebuild them;
            # keeping this id would turn exact restore into a cache coincidence.
            self.view._backdrop_id = ""
            self.view.artist = None
        except Exception:
            pass
        self._base_pack = None
        self._show_pack = None
        self._packs_open = False

    def _prepare(self, player, deck):
        """Load via Nametag, collect, retry once, then latch lights-only.

        `artist is None` is the outcome to test: the total glyph reader contains
        allocation errors itself, so relying only on a raised MemoryError would
        silently skip the required retry on hardware. A failed player remains
        remembered, preventing a serial line and two flash reads every frame.
        """
        reason = "unavailable"
        for attempt in range(2):
            try:
                if not self._open_packs():
                    reason = "assets"
                else:
                    # `_glyph_artist` is the renderer's one painter factory.
                    # Calling it directly is necessary only because two effect
                    # decks are intentionally absent from `kind_of()`'s wearer
                    # catalogue; the returned artist and retained backdrop are
                    # exactly the same objects `background()` normally installs.
                    self.view.pack = self._show_pack
                    self.view._backdrop_id = deck
                    self.view.artist = self.view._glyph_artist(deck)
                if getattr(self.view, "artist", None) is not None:
                    # No show frame draws type, so sampling 189 name-band pixels
                    # here would pay composition work whose result cannot show.
                    # Exact restore rebuilds the wearer backdrop and samples it.
                    show_state = dict(self.state)
                    show_state["background"] = deck
                    self.plan = self.nametag.plan_for(
                        show_state, animate=deck)
                    return True
            except MemoryError:
                reason = "memory"
            except Exception:
                reason = "load"
            if attempt == 0:
                # Lazy for the same half-refresh reason as effect_library, and
                # because importing the helper itself must allocate nothing a
                # shipping NameError/no-service Nametag does not need.
                import gc

                gc.collect()
                self._forget_failed_deck(deck)
        # Static words only: exception reprs can contain paths or unbounded
        # payload text, while this line may be multiplied across a whole fleet.
        self.emit("POSTER_SHOW fallback=lights id=%s reason=%s"
                  % (getattr(player, "effect_id", "?"), reason))
        self.plan = None
        self._restore_packs()
        return False

    def _paint(self, player, now):
        """One deck frame with name and sticker composition absent.

        HIDE, NOT OVERLAY: composing only to cover it pays twice and still lets
        the name leak through unlit glyph cells. `Nametag.badge` is the ordinary
        retained-film path with its two existing layer switches off, so this is
        cheaper than a worn frame and owns no second player or surface.
        """
        if self.clear_pen is not None:
            self.screen.pen = self.clear_pen
            self.screen.clear()
        self.plan["now"] = self._elapsed(player, now)
        self.plan["frame"] += 1
        self.view.badge(self.plan, name=False, marks=False)

    def _preempt(self, player):
        """Finish runtime channels before wearer pixels return.

        The service preemptor writes the terminal case-light and panel values.
        Calling `player.interrupt()` here would only stage them. The identity
        check prevents a press from stopping a newer command if a hostile seam
        changes the slot between observation and this guarded call.
        """
        if self.network is None or player is None:
            return
        try:
            if getattr(self.network, "_effect", None) is not player:
                return
            stop = getattr(self.network, "_preempt_effect", None)
            if callable(stop):
                stop()
        except Exception:
            pass

    def step(self, now):
        """Paint, switch, or restore once from the current runtime slot."""
        player = self._effect()
        if player is not self.player:
            had_pixels = self.plan is not None
            self.player = player
            self.plan = None
            if player is not None:
                deck = self._deck_for(player)
                if deck:
                    self._prepare(player, deck)
            # A playable successor switches deck-to-deck. An unknown or failed
            # successor restores instead; leaving the old pixels under new
            # lights would make an unavailable command look successful.
            if self.plan is None and had_pixels:
                self._restore_packs()
                self.restore()
                return RESTORED
        if self.plan is None:
            return NONE
        try:
            self._paint(player, now)
        except Exception:
            import gc

            gc.collect()
            self.emit("POSTER_SHOW fallback=lights id=%s reason=frame"
                      % getattr(player, "effect_id", "?"))
            # Drop show RAM before restore: if the repaint fails, no later frame
            # may treat stale fleet state as authority and cover the fallback.
            self.plan = None
            self._restore_packs()
            self.restore()
            return RESTORED
        return PAINTED

    def press(self):
        """A wearer press ends the glyph show before restoring their pixels."""
        # The doorbell can seat a player before Nametag's first update. Observe
        # that slot here too, or a press on that exact frame would exit before
        # `step()` saw it and leave the fleet effect owning the case lights.
        player = self.player or self._effect()
        had_pixels = self.plan is not None
        self._preempt(player)
        self.player = None
        self.plan = None
        if had_pixels:
            self._restore_packs()
            self.restore()

    def exit(self):
        """HOME may bypass another frame, so retire runtime channels here too."""
        # Match `press`: an app exit can race the first observed show frame.
        self._preempt(self.player or self._effect())
        self.player = None
        self.plan = None
        self._restore_packs()
