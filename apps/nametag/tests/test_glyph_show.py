"""The fleet glyph effect is a temporary, fail-soft Nametag backdrop.

This boots the shipping entry module rather than modelling a second show loop.
The fakes stop at Badgeware's injected graphics boundary, so the assertions see
the same composition flags, state object and BadgeLink slot the badge sees.
"""

import ast
import builtins
import contextlib
import importlib.util
import io
import pathlib
import subprocess
import sys
import types
import unittest


# APP COMES FROM THE HARNESS, and this file was the one module in the directory
# that computed its own. `parents[1] / "badge" / "nametag"` reconstructs the
# REPOSITORY unconditionally, so from the source export -- where the payload is
# flattened into `apps/nametag/` and no `badge/nametag` exists -- it aimed at a
# directory that cannot be there: 17 of this file's cases failed and 14 of them
# named that path. The harness asks the filesystem which layout it is in, and
# this suite imports it anyway for the `sys.path` side effect.
from nametag_harness import APP, requires_repository

ENTRY = APP / "__init__.py"

# THE TWO SHAPES THE RUNTIME CAN BE IN, tried in this order at every parent.
# The protocol table is the one source of truth for ids and pack membership, and
# a copied test list was exactly the applied-once trap when the first eight grew,
# so this must find the REAL table or refuse: it may not fall back to a literal.
_EFFECT_LAYOUTS = (
    ("badgelink", "badge", "badgelink", "effect_library.py"),   # the repository
    ("lib", "effect_library.py"),                               # the export
)


def _effect_library_path():
    """The first `effect_library.py` that exists, walking upward.

    Asking the filesystem beats counting parents: a reviewer who copies either
    tree one directory deeper still gets the right answer. The repository shape
    is FIRST at every level on purpose, so a repository checkout that also has a
    stray top-level `lib/` still resolves to the real runtime.
    """
    here = pathlib.Path(__file__).resolve()
    tried = []
    for parent in here.parents:
        for shape in _EFFECT_LAYOUTS:
            candidate = parent.joinpath(*shape)
            tried.append(candidate)
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(
        "no effect_library.py found from %s; tried:\n  %s"
        % (here, "\n  ".join(str(path) for path in tried)))


_EFFECT_SPEC = importlib.util.spec_from_file_location(
    "nametag_test_effect_library", _effect_library_path())
EFFECT_LIBRARY = importlib.util.module_from_spec(_EFFECT_SPEC)
_EFFECT_SPEC.loader.exec_module(EFFECT_LIBRARY)

DECKS = dict(enumerate(row[0] for row in EFFECT_LIBRARY.GLYPH_EFFECTS))


class Effect:
    def __init__(self, effect_id, kind="glyph", skew_ms=0):
        self.kind = kind
        self.effect_id = effect_id
        self.skew_ms = skew_ms
        self.done = False


class Network:
    def __init__(self):
        self._effect = None
        self._effect_started = 0
        self.active = []
        self.preempted = []

    def set_active(self, active):
        self.active.append(bool(active))

    def _preempt_effect(self):
        effect = self._effect
        if effect is not None:
            effect.done = True
            self.preempted.append(effect)
        self._effect = None


class FakeBadge:
    def __init__(self):
        self.default_clear = (0, 0, 0)
        self.down = False
        self.modes = []
        self.lights = []

    def mode(self, mode):
        self.modes.append(mode)

    def caselights(self, level):
        self.lights.append(level)

    def pressed(self):
        return self.down


class FakeScreen:
    width = 320
    height = 240

    def __init__(self):
        self.pen = None
        self.font = None
        self.clears = 0

    def clear(self):
        self.clears += 1

    def text(self, *_args):
        return None


class FakeView:
    def __init__(self, harness):
        self.harness = harness
        self.artist = None
        self._backdrop_id = ""
        self.effect = "none"
        self.effect_applied = "none"
        self.hits = 0
        self.renders = 0
        self.cache_stamp = 0
        self._pack = types.SimpleNamespace(
            masks=lambda *_args: b"mask", lut=lambda *_args: b"lut")

    @property
    def pack(self):
        return self._pack

    @pack.setter
    def pack(self, value):
        self._pack = value

    def name(self, plan):
        self.harness.compositions.append({
            "stage": "name", "background": plan["state"]["background"],
            "name": True, "marks": False,
        })

    def background(self, entry_id):
        self.harness.loads.append(entry_id)
        self.artist = object()
        self._backdrop_id = entry_id
        return object()

    def _glyph_artist(self, entry_id):
        self.harness.loads.append(entry_id)
        outcome = (self.harness.load_outcomes.pop(0)
                   if self.harness.load_outcomes else "ok")
        if outcome == "memory":
            raise MemoryError("injected deck allocation")
        if outcome == "missing":
            self.artist = None
        else:
            self.artist = object()
        return self.artist

    def _sample_ink(self, _entry_id):
        return None

    def badge(self, plan, skip=-1, name=True, marks=True):
        del skip
        self.background(plan["state"]["background"])
        self.harness.paint_order.append(
            (plan["state"]["background"],
             len(self.harness.network.preempted)
             if self.harness.network is not None else 0))
        self.harness.compositions.append({
            "stage": "badge",
            "background": plan["state"]["background"],
            "name": bool(name),
            "marks": bool(marks),
            "brightness": plan["state"]["brightness"],
            "now": plan["now"],
            "stickers": tuple(mark["kind"]
                              for mark in plan["state"]["stickers"]),
        })

    def worn(self, plan, marks=True):
        self.badge(plan, name=True, marks=marks)


class AppHarness:
    """Execute the real entry module with Badgeware-shaped injected globals."""

    GLOBALS = (
        "badge", "display", "screen", "color", "font", "image", "vec2",
        "rect", "run", "HIRES", "VSYNC", "badgelink_network",
    )

    def __init__(self, network=True, library=True, source=None,
                 load_outcomes=()):
        self.network = Network() if network else None
        self.badge = FakeBadge()
        self.screen = FakeScreen()
        self.ticks = 1000
        self.printed = []
        self.compositions = []
        self.paint_order = []
        self.loads = []
        self.load_outcomes = list(load_outcomes)
        self.gc_collects = 0
        self.state = {
            "name": "SAM",
            "line2": "SELECT",
            "face": "winds",
            "background": "skin.supabase",
            "stickers": ({"kind": "github", "x": 0.2, "y": 0.3},),
            "motion": False,
            "brightness": 55,
            "effect": "none",
        }
        self.original_state = {
            key: value for key, value in self.state.items()
        }
        self._saved_builtins = {
            name: getattr(builtins, name, None) for name in self.GLOBALS
        }
        self._had_builtin = {
            name: hasattr(builtins, name) for name in self.GLOBALS
        }
        self._saved_modules = {}
        self._saved_path = list(sys.path)
        # The device importer has the app directory at the front. The harness
        # executes a source string, so it must supply that one import fact.
        sys.path.insert(0, str(APP))
        self._closed = False

        display = types.SimpleNamespace(
            update=lambda: None,
            backlight=lambda level: self.printed.append(
                "BACKLIGHT %.3f" % level),
        )
        color = types.SimpleNamespace(
            rgb=lambda *channels: tuple(channels), white=(255, 255, 255))
        values = {
            "badge": self.badge,
            "display": display,
            "screen": self.screen,
            "color": color,
            "font": types.SimpleNamespace(sins="sins"),
            "image": object(),
            "vec2": lambda x, y: (x, y),
            "rect": lambda *values: values,
            "run": lambda update: setattr(self, "update", update),
            "HIRES": 4,
            "VSYNC": 2,
        }
        if self.network is not None:
            values["badgelink_network"] = self.network
        for name, value in values.items():
            setattr(builtins, name, value)
        if self.network is None and hasattr(builtins, "badgelink_network"):
            delattr(builtins, "badgelink_network")

        fake_view_module = types.SimpleNamespace(
            DARK_RGB=(9, 14, 24),
            cache_stamp=lambda _root: 0,
            plan_for=lambda state, now_ms=0, frame=0, animate=None: {
                "state": state,
                "animate": (state["background"] if state["motion"]
                            else "") if animate is None else animate,
                "now": now_ms,
                "frame": frame,
            },
            Nametag=lambda *_args: self._new_view(),
        )
        modules = {
            "badgeware": types.SimpleNamespace(),
            "badge_state": types.SimpleNamespace(
                read=lambda _path: self.state, source="fixture"),
            "nametag": fake_view_module,
            "ui": types.SimpleNamespace(Chrome=lambda: object()),
            "backlight": types.SimpleNamespace(
                fraction=lambda pct: float(pct) / 100.0),
            "time": types.SimpleNamespace(
                ticks_ms=lambda: self.ticks,
                ticks_diff=lambda later, earlier: later - earlier),
            "gc": types.SimpleNamespace(collect=self._collect),
        }
        if library:
            modules["effect_library"] = types.SimpleNamespace(
                describe=lambda kind, effect_id: (
                    {"kind": kind, "id": effect_id,
                     "name": DECKS[effect_id]}
                    if kind == "glyph" and effect_id in DECKS else None))
        else:
            modules["effect_library"] = None
        for name, module in modules.items():
            self._saved_modules[name] = sys.modules.get(name)
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

        namespace = {
            "__name__": "poster_test_app",
            "print": lambda *parts: self.printed.append(
                " ".join(str(part) for part in parts)),
        }
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(source or ENTRY.read_text(), str(ENTRY), "exec"),
                     namespace)
        except BaseException:
            self.close()
            raise
        self.namespace = namespace

    def _new_view(self):
        self.view = FakeView(self)
        return self.view

    def _collect(self):
        self.gc_collects += 1

    def close(self):
        if self._closed:
            return
        self._closed = True
        for name in self.GLOBALS:
            if self._had_builtin[name]:
                setattr(builtins, name, self._saved_builtins[name])
            elif hasattr(builtins, name):
                delattr(builtins, name)
        for name, module in self._saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        sys.path[:] = self._saved_path

    def frame(self, pressed=False, advance=100):
        self.ticks += advance
        self.badge.down = pressed
        saved = pathlib.Path.cwd()
        try:
            # Relative asset paths are resolved from the launched app on the
            # badge; reproduce that instead of weakening production paths.
            import os
            os.chdir(APP)
            return self.update()
        finally:
            os.chdir(saved)

    def play(self, effect_id, kind="glyph", skew_ms=0):
        effect = Effect(effect_id, kind=kind, skew_ms=skew_ms)
        self.network._effect = effect
        self.network._effect_started = self.ticks
        return effect

    def show_frames(self):
        return [row for row in self.compositions
                if row["stage"] == "badge"
                and row["background"].startswith("glyph.")]

    def wearer_frames(self):
        return [row for row in self.compositions
                if row["stage"] == "badge"
                and row["background"] == self.state["background"]]


class GlyphShowTests(unittest.TestCase):
    def harness(self, **kwargs):
        harness = AppHarness(**kwargs)
        self.addCleanup(harness.close)
        return harness

    def test_A_SHOW_FRAME_NEVER_DRAWS_THE_NAME_OR_STICKERS(self):
        """Failing-first repro: a normal Nametag paint draws SAM over the deck."""
        app = self.harness()
        app.play(0)
        app.frame()
        self.assertTrue(app.show_frames(), "the commanded deck was not drawn")
        self.assertTrue(all(not row["name"] and not row["marks"]
                            for row in app.show_frames()),
                        "a show frame kept the name or stickers visible")

    def test_unknown_effect_id_stays_lights_only(self):
        app = self.harness()
        app.play(len(DECKS))
        app.frame()
        self.assertEqual([], app.show_frames())
        self.assertEqual([], [path for path in app.loads
                              if path.startswith("glyph.")])

    def test_a_deck_memory_error_collects_retries_once_then_latches_lights(self):
        app = self.harness()
        app.load_outcomes[:] = ("memory", "memory")
        effect = app.play(1)
        app.frame()
        app.frame()
        self.assertIs(effect, app.network._effect,
                      "nametag changed the runtime's ack/effect ownership")
        self.assertEqual(1, app.gc_collects)
        self.assertEqual(2, app.loads.count("glyph.wave"))
        lines = [line for line in app.printed
                 if line.startswith("POSTER_SHOW fallback=lights")]
        self.assertEqual(1, len(lines), lines)
        self.assertLessEqual(len(lines[0]), 96)

    def test_two_back_to_back_shows_do_not_flash_the_wearer_between_them(self):
        app = self.harness()
        first = app.play(0)
        app.frame()
        before = len(app.compositions)
        second = app.play(7)
        app.frame()
        rows = [row for row in app.compositions[before:]
                if row["stage"] == "badge"]
        self.assertEqual("glyph.arrow-field", rows[-1]["background"])
        self.assertFalse(any(row["background"] == "skin.supabase"
                             for row in rows))
        self.assertIsNot(first, second)
        app.network._effect = None
        app.frame()
        restored = app.wearer_frames()[-1]
        self.assertTrue(restored["name"] and restored["marks"])
        self.assertEqual(app.original_state, app.state)

    def test_natural_finish_restores_the_exact_wearer_composition(self):
        app = self.harness()
        app.play(2)
        app.frame()
        app.network._effect = None
        before = len(app.compositions)
        app.frame()
        restored = [row for row in app.compositions[before:]
                    if row["stage"] == "badge"][-1]
        self.assertEqual({
            "stage": "badge", "background": "skin.supabase",
            "name": True, "marks": True, "brightness": 55,
            "now": 0, "stickers": ("github",),
        }, restored)
        self.assertEqual(app.original_state, app.state)

    def test_a_wearer_press_preempts_then_restores_before_exit(self):
        app = self.harness()
        effect = app.play(3)
        app.frame()
        before = len(app.compositions)
        self.assertEqual("exit", app.frame(pressed=True))
        self.assertEqual([effect], app.network.preempted)
        restored = [row for row in app.compositions[before:]
                    if row["stage"] == "badge"][-1]
        self.assertEqual("skin.supabase", restored["background"])
        self.assertTrue(restored["name"] and restored["marks"])
        self.assertEqual(("skin.supabase", 1), app.paint_order[-1],
                         "wearer pixels returned before runtime preemption")
        self.assertEqual(app.original_state, app.state)

    def test_a_press_before_the_first_show_frame_still_preempts_the_effect(self):
        app = self.harness()
        effect = app.play(3)
        self.assertEqual("exit", app.frame(pressed=True))
        self.assertEqual([effect], app.network.preempted)
        self.assertEqual([], app.show_frames())

    def test_shipping_NameError_branch_is_a_plain_poster(self):
        app = self.harness(network=False, library=False)
        before = len(app.compositions)
        app.frame()
        self.assertFalse(hasattr(app.namespace.get("_network"), "_effect"))
        painted = [row for row in app.compositions[before:]
                   if row["stage"] == "badge"]
        self.assertEqual(1, len(painted))
        self.assertEqual("skin.supabase", painted[0]["background"])
        self.assertTrue(painted[0]["name"] and painted[0]["marks"])
        self.assertEqual(app.original_state, app.state)

    def test_a_service_with_no_effect_library_falls_back_to_lights_only(self):
        app = self.harness(library=False)
        effect = app.play(0)
        app.frame()
        self.assertIs(effect, app.network._effect)
        self.assertEqual([], app.show_frames())

    def test_restore_ordering_gate_rejects_a_sabotaged_missing_repaint(self):
        """Prove the exact-restore assertion fails if restore drops its paint."""
        source = ENTRY.read_text()
        needle = "        _paint()  # GLYPH_SHOW_RESTORE"
        self.assertIn(needle, source, "restore's sabotage marker moved")
        broken = source.replace(needle, "        pass  # sabotaged repaint", 1)
        app = self.harness(source=broken)
        app.play(4)
        app.frame()
        app.network._effect = None
        before = len(app.compositions)
        app.frame()
        restored = [row for row in app.compositions[before:]
                    if row["stage"] == "badge"
                    and row["background"] == "skin.supabase"]
        self.assertEqual([], restored,
                         "the sabotage unexpectedly produced a wearer repaint")

    def test_press_order_gate_rejects_restore_before_runtime_preemption(self):
        source_path = APP / "glyph_show.py"
        source = source_path.read_text()
        good = """        self._preempt(player)
        self.player = None
        self.plan = None
        if had_pixels:
            self._restore_packs()
            self.restore()
"""
        bad = """        self.player = None
        self.plan = None
        if had_pixels:
            self._restore_packs()
            self.restore()
        self._preempt(player)  # sabotaged: fleet channels act last
"""
        self.assertIn(good, source, "press ordering shape moved")
        broken = types.ModuleType("glyph_show")
        exec(compile(source.replace(good, bad, 1), str(source_path), "exec"),
             broken.__dict__)
        saved = sys.modules.get("glyph_show")
        sys.modules["glyph_show"] = broken

        def restore_module():
            if saved is None:
                sys.modules.pop("glyph_show", None)
            else:
                sys.modules["glyph_show"] = saved

        self.addCleanup(restore_module)
        app = self.harness()
        app.play(3)
        app.frame()
        app.frame(pressed=True)
        self.assertEqual(("skin.supabase", 0), app.paint_order[-1],
                         "the sabotage did not restore before preemption")


class GlyphShowAssetTests(unittest.TestCase):
    # Shells out to `nametag/host/build_glyph_show_assets.py`, a host builder
    # the source export omits on purpose.
    @requires_repository
    def test_the_show_pack_is_reproducible_from_every_library_row(self):
        result = subprocess.run(
            [sys.executable, str(APP.parents[1] / "host" /
                                 "build_glyph_show_assets.py"), "--check"],
            cwd=APP.parents[2], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("members=%d" % len(EFFECT_LIBRARY.GLYPH_EFFECTS),
                      result.stdout)

    def test_pack_membership_equals_the_effect_library_both_directions(self):
        sys.path.insert(0, str(APP))
        self.addCleanup(lambda: sys.path.remove(str(APP)))
        import glyphskin

        streams = glyphskin.open_pack(
            str(APP / "assets" / "glyphshows.gpk"))
        self.assertIsNotNone(streams)
        self.assertEqual(set(DECKS.values()), set(streams.techniques()))

    # Loads `identity/host/build_skin_assets.py`, the archived editor's builder,
    # which the export omits for the same reason.
    @requires_repository
    def test_all_numbered_streams_build_real_hires_skin_artists(self):
        builder_path = APP.parents[2] / "identity" / "host" / \
            "build_skin_assets.py"
        spec = importlib.util.spec_from_file_location(
            "poster_show_surface", builder_path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        sys.path.insert(0, str(APP))
        self.addCleanup(lambda: sys.path.remove(str(APP)))
        import glyph_show
        import glyphskin

        resources = glyphskin.open_pack(
            str(APP / "assets" / "glyphskins.gpk"))
        streams = glyphskin.open_pack(
            str(APP / "assets" / "glyphshows.gpk"))
        pack = glyph_show._ShowPack(streams, resources)
        for name in DECKS.values():
            with self.subTest(name=name):
                surface = builder.PreviewSurface(320, 240)
                artist = glyphskin.skin(
                    pack, "glyph." + name, surface, builder.PreviewSurface,
                    lambda x, y: (x, y), glyphskin.VIVID, budget=0)
                self.assertIsNotNone(artist)
                self.assertEqual(384, artist.advance(0))
                self.assertTrue(artist.caught_up)

    def test_every_numbered_effect_can_reach_a_deck_frame(self):
        app = AppHarness()
        self.addCleanup(app.close)
        for effect_id, name in DECKS.items():
            with self.subTest(effect_id=effect_id, name=name):
                app.play(effect_id)
                app.frame()
                self.assertEqual("glyph." + name,
                                 app.show_frames()[-1]["background"])

    def test_execute_at_skew_is_part_of_the_pixel_clock(self):
        app = AppHarness()
        self.addCleanup(app.close)
        app.play(0, skew_ms=700)
        app.frame(advance=125)
        self.assertEqual(825, app.show_frames()[-1]["now"])

    def test_the_show_never_reads_or_writes_the_brightness_seam(self):
        tree = ast.parse((APP / "glyph_show.py").read_text())
        identifiers = {
            getattr(node, "id", None) or getattr(node, "attr", None)
            for node in ast.walk(tree)
        }
        self.assertNotIn("note_panel_level", identifiers)
        self.assertNotIn("_panel_base", identifiers)


if __name__ == "__main__":
    unittest.main()
