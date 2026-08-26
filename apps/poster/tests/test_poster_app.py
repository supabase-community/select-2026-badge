"""Guards on the app itself: what it may import, when, and what it may write.

The browser lane proves the app draws identity's picture. These are the
properties a picture cannot show:

*   THE APP IS READ-ONLY.  No `open(..., "w")`, no `os.remove`, no import of
    `identity_store`. The badge's state file is the editor's, and the one
    unrecoverable data-loss shape in this repository lives behind `erase`.
*   THE STAGES ARE IN THE RIGHT ORDER IN THE SOURCE.  A staged arrival is
    entirely a property of statement order in a module body -- there is no
    scheduler and no thread -- so "the field is painted before the first
    import" is an assertion about the AST, and the browser lane's frame film
    is what proves the panel agrees.
*   NOTHING PULLS IN THE EDITOR.  85,227 bytes of `identity_app` and 48,490 of
    `identity_model` are the entire reason this app exists.
*   THE VENDORED COPIES ARE THE CANONICAL BYTES.  Twelve of the fourteen files here
    are copies `scripts/sync_ui.py` owns; a copy it does not know about rots
    silently.
"""

import ast
import os
import pathlib
import hashlib
import importlib.util
import subprocess
import tempfile
import unittest

import poster_harness
from poster_harness import APP, REPO, requires_repository


ENTRY = APP / "__init__.py"
SOURCE = ENTRY.read_text()
TREE = ast.parse(SOURCE)

# What the app's own two files may import. Everything else is vendored and
# checked by its own suite.
# `backlight` joined on 2026-08-23 with the owner's idle design. It is the
# smallest module in the app -- it imports nothing at all -- and it is here
# rather than in the FORBIDDEN table for the reason that table exists: it names
# the EDITOR's heavy modules, and stage 1's whole claim is that it parses none
# of them.
#
# `idle` was allowed here too until the 2026-08-24 ruling that the poster never
# dims. It is deliberately NOT in this set now, so an `import idle` fails the
# import gate as well as `IdleTests`.
ALLOWED = {"sys", "time", "json", "badgeware", "badge_state", "poster", "ui",
           "backlight"}
FORBIDDEN = {
    "identity_app": "the controller, 85,227 B",
    "identity_model": "the schema, 48,490 B",
    "identity_store": "the WRITER",
    "identity_view": "the editor's ten screens, 92,412 B",
    "identity_keyboard": "the on-screen keyboard",
    "wallpaper": "the film codec",
    "wallpaper_bake": "the film baker",
}


def imports_of(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module.split(".")[0], node.lineno))
    return found


class ImportTests(unittest.TestCase):
    def test_the_entry_file_imports_only_what_it_needs(self):
        extra = {name for name, _line in imports_of(TREE)} - ALLOWED
        self.assertEqual(extra, set(), "unexpected imports: %s" % sorted(extra))

    def test_the_editor_is_not_reachable(self):
        for module in (APP / "badge_state.py", ENTRY):
            names = {name for name, _line in
                     imports_of(ast.parse(module.read_text()))}
            hit = names.intersection(FORBIDDEN)
            self.assertEqual(hit, set(), "%s imports %s (%s)" % (
                module.name, sorted(hit),
                "; ".join(FORBIDDEN[name] for name in sorted(hit))))

    def test_no_module_in_the_app_imports_out_of_another_app_directory(self):
        """A vendored copy that reaches for `/system/apps/identity` is a badge
        app that refuses to start when the editor is not installed -- the one
        failure mode this arrangement pays 650 KB of flash to avoid."""
        for path in sorted(APP.glob("*.py")):
            text = path.read_text()
            self.assertNotIn('sys.path.insert(0, "/system/apps/identity',
                             text, path.name)


class StageOrderTests(unittest.TestCase):
    """The arrival is statement order, so it is checkable as statement order.

    Threads are compiled out, so nothing between two statements here can
    interleave: the panel shows exactly what the last `display.update()` drew,
    for exactly as long as the next statement takes.
    """

    def body_lines(self):
        """(kind, lineno) for the module body, in source order."""
        rows = []
        for node in TREE.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for name, line in imports_of(node):
                    rows.append(("import:" + name, line))
            else:
                rows.append((type(node).__name__, node.lineno))
        return rows

    def first_line_of(self, text):
        for number, line in enumerate(SOURCE.split("\n"), 1):
            if text in line and not line.strip().startswith("#"):
                return number
        self.fail("not in the entry file: %s" % text)

    def test_the_field_is_painted_before_the_first_app_import(self):
        painted = self.first_line_of("_stage(0)")
        for name in ("badge_state", "poster", "ui"):
            line = min(number for imported, number in self.body_lines()
                       if imported == "import:" + name)
            self.assertGreater(line, painted,
                               "%s is imported before stage 0 reaches the "
                               "panel" % name)

    def test_the_mode_is_set_before_anything_is_drawn(self):
        """`badge.mode` rebinds `builtins.screen`, so a paint before it is a
        paint into a surface the panel is about to throw away."""
        self.assertLess(self.first_line_of("badge.mode("),
                        self.first_line_of("screen.clear()"))

    def test_the_stages_are_presented_in_order(self):
        for earlier, later in (("_stage(0)", "_try(1"), ("_try(1", "_try(2"),
                               ("_try(2", "_try(3")):
            self.assertLess(self.first_line_of(earlier),
                            self.first_line_of(later),
                            "%s must be presented before %s" % (earlier, later))

    def test_the_marks_stage_is_conditional_on_there_being_marks(self):
        """An `image.load` of the mark sheet is 38-78 ms extrapolated at LORES
        and a badge with no stickers has no reason to pay it."""
        self.assertIn('state["stickers"]:', SOURCE)

    def test_the_run_loop_is_the_last_statement(self):
        last = TREE.body[-1]
        self.assertIsInstance(last, ast.Expr)
        self.assertEqual(getattr(last.value.func, "id", None), "run")


SEAM_CALL = "badge.mode(HIRES | VSYNC)"
PANEL_MODES = {"LORES", "HIRES"}


def app_modules():
    """Every module in the app package, subpackages included.

    `rglob`, not `glob`: with `glob` a module in a subdirectory was invisible to
    the guard, and "one panel decision in this package" is a claim about the
    whole tree.  `__pycache__` is a build artifact.
    """
    return sorted(path for path in APP.rglob("*.py")
                  if "__pycache__" not in path.parts)


def mode_calls(tree):
    """Every `badge.mode(...)` in a parsed module, not just the first."""
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "mode"
            and getattr(node.func.value, "id", None) == "badge"]


def panel_names(tree, allowed_calls=()):
    """`LORES`/`HIRES` name nodes, minus the ones inside an allowed call."""
    exempt = set()
    for call in allowed_calls:
        exempt.update(id(node) for node in ast.walk(call))
    return sorted(node.id for node in ast.walk(tree)
                  if isinstance(node, ast.Name) and node.id in PANEL_MODES
                  and id(node) not in exempt)


class ResolutionTests(unittest.TestCase):
    """HIRES, decided once, in the seam -- the owner's ruling of 2026-08-21.

    The idiom is `badgecard`'s, which proved it: the panel is chosen in the
    entry file and every module downstream reads the resolution off the SURFACE
    it was handed.  A second place that names a mode is a second place two
    resolutions can disagree, and the way that fails is silent -- both canvases
    are valid, so the wrong one renders correctly and merely looks wrong.

    A DRIFT-CATCHER, NOT A SANDBOX.  It reads the AST, so it catches what
    actually happens: a well-meant second `badge.mode` call, or a module that
    names a mode.  It does not chase evasion -- `getattr(builtins, "HIRES")`, a
    flag through a variable, a mode assembled in a string and `exec`ed -- and it
    should not be extended to.  Anyone writing that is not drifting.

    Both of the holes this class had until 2026-08-21 were the SHAPE of the
    walk rather than its subject: `test_the_seam_opens_the_panel_at_hires`
    returned on the first `.mode` match, so a second `badge.mode(LORES | VSYNC)`
    on the next line passed, and the module walk used `glob` and skipped the
    entry file wholesale.
    """

    def test_the_seam_opens_the_panel_at_hires(self):
        """COUNTED, not found.  This used to `return` on the first match."""
        calls = mode_calls(TREE)
        self.assertEqual(1, len(calls), "one mode decision, or none at all")
        self.assertEqual(SEAM_CALL, ast.unparse(calls[0]))

    def test_the_seam_names_a_mode_only_inside_that_one_call(self):
        """The entry file is CHECKED, not exempted: the allowance is the CALL.

        `HIRES` and `VSYNC` belong in `badge.mode(HIRES | VSYNC)`.  Exempting
        the FILE meant a second decision beside the first was invisible;
        allowing the call by identity means the first is fine and the second
        brings name nodes that are not in the exempt set.
        """
        self.assertEqual([], panel_names(TREE, mode_calls(TREE)))

    def test_nothing_but_the_seam_names_a_panel_mode(self):
        """AST, not text: every other module in this app DISCUSSES both
        resolutions in its comments, and that is fine.  What must not exist is a
        module that READS one."""
        for path in app_modules():
            tree = ast.parse(path.read_text())
            allowed = mode_calls(tree) if path == ENTRY else ()
            if allowed:
                self.assertEqual(1, len(allowed), path.name)
            self.assertEqual([], panel_names(tree, allowed), path.name)

    def test_no_module_but_the_seam_calls_badge_mode_at_all(self):
        """The panel is not merely NAMED once, it is SET once.

        The name walk above passes a module holding `badge.mode(flag)` -- no
        `LORES`/`HIRES` node anywhere, and a second panel decision all the same.
        There is exactly one `badge.mode` call in this package.
        """
        found = {}
        for path in app_modules():
            calls = mode_calls(ast.parse(path.read_text()))
            if calls:
                found[path.name] = [ast.unparse(call) for call in calls]
        self.assertEqual({"__init__.py": [SEAM_CALL]}, found)

    def test_the_only_mark_sheet_that_exists_is_the_hires_one(self):
        """Why HIRES is not merely preferred here.  The 24 px 1-bit sheet was
        deleted from every app when the stickers went HIRES, so a LORES
        `chrome.scale == 1` would take `poster.marks`'s no-sheet path and draw
        hollow squares where the wearer's marks are."""
        assets = APP / "assets"
        self.assertTrue((assets / "stickers-36-p8.png").is_file())
        self.assertFalse((assets / "stickers-24-p8.png").exists(),
                         "the LORES mark sheet is back; this app's resolution "
                         "ruling and its assets have to agree")


class BackdropCacheTests(unittest.TestCase):
    """The cache is READ here and written by the editor, and that split is the
    read-only ruling above meeting the owner's 2026-08-21 latency verdict.

    `shared/backdrop.py` carries a writer; this app vendors it because
    `shared/poster.py` imports one module, not half of one. So the property
    worth asserting is not "no writer exists in the directory" -- it does -- but
    that NOTHING THIS APP OWNS CALLS IT.
    """

    OWN = ("__init__.py", "badge_state.py")

    def calls_in_own_files(self):
        found = set()
        for name in self.OWN:
            for node in ast.walk(ast.parse((APP / name).read_text())):
                if not isinstance(node, ast.Call):
                    continue
                attribute = getattr(node.func, "attr", None)
                if attribute:
                    found.add(attribute)
                name_id = getattr(node.func, "id", None)
                if name_id:
                    found.add(name_id)
        return found

    def test_the_app_never_reaches_the_cache_writer(self):
        called = self.calls_in_own_files()
        for writer in ("backdrop_writer", "save", "Writer", "abandon",
                       "persist_backdrop"):
            self.assertNotIn(writer, called,
                             "the badge app calls %s; the cache is the "
                             "EDITOR's to fill" % writer)

    def test_the_cache_is_armed_between_the_name_and_the_artwork(self):
        """A stamp taken before stage 1 would put a file read and a codec parse
        in front of the wearer's name, which is the one thing the staged
        arrival exists to protect."""
        source = SOURCE
        named = source.index("_try(1, _name_only)")
        armed = source.index("cache_stamp")
        artwork = source.index("_try(2,")
        self.assertLess(named, armed, "the cache is armed before the name")
        self.assertLess(armed, artwork, "the cache is armed after the artwork")

    def test_the_codec_is_vendored_beside_the_renderer(self):
        self.assertTrue((APP / "backdrop.py").is_file(),
                        "the renderer imports `backdrop`; run: python3 "
                        "scripts/sync_ui.py")

    def test_the_oracle_line_is_printed(self):
        """`hits=1 renders=0` against `hits=0 renders=1` is the only way a test
        can tell a cached arrival from a rendered one -- both draw the same
        picture, which is the entire point."""
        self.assertIn("POSTER_CACHE hits=%d renders=%d", SOURCE)


class ReadOnlyTests(unittest.TestCase):
    """The badge app is a second WINDOW onto one badge, not a second badge."""

    # `poster.py`, `ui.py` and the artwork modules are vendored and have their
    # own suites; these are the two files this app writes.
    OWN = ("__init__.py", "badge_state.py")

    def test_nothing_the_app_owns_can_write_or_delete(self):
        """Read from the AST, not from the text.

        A substring search over source hits the docstring that EXPLAINS why
        there is no write here, which is a test that fails when the prose
        improves -- the mistake `identity/tests/test_identity_app.py` records
        having made and fixed.
        """
        destructive = {"remove", "unlink", "rename", "rmdir", "mkdir",
                       "truncate"}
        for name in self.OWN:
            tree = ast.parse((APP / name).read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if getattr(node.func, "id", None) == "open":
                    modes = [ast.literal_eval(arg) for arg in node.args[1:]
                             if isinstance(arg, ast.Constant)]
                    self.assertEqual(modes, [], "%s: open() with a mode" % name)
                    for keyword in node.keywords:
                        self.assertNotEqual(keyword.arg, "mode", name)
                attribute = getattr(node.func, "attr", None)
                self.assertNotIn(attribute, destructive,
                                 "%s calls %s" % (name, attribute))

    def test_the_only_open_is_the_state_read(self):
        opens = [node for node in ast.walk(ast.parse(
            (APP / "badge_state.py").read_text()))
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "open"]
        self.assertEqual(len(opens), 1)
        self.assertEqual(len(opens[0].args), 1,
                         "a second argument to open() is a mode, and the only "
                         "mode this app may use is the default read")


class ConstantTests(unittest.TestCase):
    def test_the_stage_zero_field_is_the_poster_s_own_dark(self):
        """Stage 0 paints before `poster` is imported, so its colour is a
        literal here. This is what stops the literal drifting: the field the
        wearer sees first and the field the renderer uses must be one colour."""
        import poster

        for node in TREE.body:
            if (isinstance(node, ast.Assign)
                    and getattr(node.targets[0], "id", None) == "DARK"):
                literal = ast.literal_eval(node.value)
                break
        else:
            self.fail("the entry file no longer defines DARK")
        self.assertEqual(literal, poster.DARK_RGB)

    def test_the_state_path_is_the_badge_editor_s_own(self):
        """Two apps, one file, and the path is pinned against the WRITER.

        Retargeted 2026-08-17 from `identity_store.STATE_PATH` to
        `card_store.STATE_PATH`: `badgecard` is the editor the owner ships and
        this app is the launcher hold's fast window onto it.  The assertion is
        still against the writer's own constant rather than a literal, which is
        the property that matters -- a viewer reading a path nobody writes is a
        viewer that shows a blank badge for ever and says nothing about why.
        """
        import sys
        card = poster_harness.sibling_app("badgecard")
        if card is None:
            self.skipTest("badgecard is not in this tree, and its STATE_PATH "
                          "constant is the thing this pins against")
        if str(card) not in sys.path:
            sys.path.append(str(card))
        import card_store

        for node in TREE.body:
            if (isinstance(node, ast.Assign)
                    and getattr(node.targets[0], "id", None) == "STATE_PATH"):
                self.assertEqual(ast.literal_eval(node.value),
                                 card_store.STATE_PATH)
                return
        self.fail("the entry file no longer defines STATE_PATH")


@requires_repository
class ProvenanceTests(unittest.TestCase):
    """Twelve of the fourteen files here are copies. The script owns every one."""

    OWN = ("__init__.py", "badge_state.py")

    def table(self):
        spec = importlib.util.spec_from_file_location(
            "sync_ui", str(REPO / "scripts" / "sync_ui.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.MODULES

    def vendored(self):
        here = str(APP.relative_to(REPO))
        found = {}
        for canonical, consumers in self.table():
            for relative in consumers:
                if relative.startswith(here + "/"):
                    found[relative] = canonical
        return found

    def test_every_file_is_either_ours_or_vendored(self):
        vendored = self.vendored()
        for path in sorted(APP.rglob("*")):
            if not path.is_file() or "__pycache__" in str(path):
                continue
            relative = str(path.relative_to(REPO))
            if path.name in self.OWN:
                continue
            self.assertIn(relative, vendored,
                          "%s is neither the app's own code nor a copy "
                          "scripts/sync_ui.py knows about" % relative)

    def test_every_vendored_copy_is_byte_identical(self):
        for relative, canonical in sorted(self.vendored().items()):
            want = hashlib.sha256((REPO / canonical).read_bytes()).hexdigest()
            got = hashlib.sha256((REPO / relative).read_bytes()).hexdigest()
            self.assertEqual(got, want, "%s has drifted from %s -- run: "
                             "python3 scripts/sync_ui.py"
                             % (relative, canonical))

    def test_the_renderer_is_the_one_identity_draws_with(self):
        """The whole claim, as a hash. If these two files ever differ, the two
        apps are two renderings and every pixel comparison downstream is
        measuring a coincidence."""
        mine = hashlib.sha256((APP / "poster.py").read_bytes()).hexdigest()
        theirs = hashlib.sha256(
            (poster_harness.IDENTITY / "poster.py").read_bytes()).hexdigest()
        self.assertEqual(mine, theirs)


class NoLoadingScreenTests(unittest.TestCase):
    """THIS APP HAS NO LOADING SCREEN AND MUST NEVER GROW ONE.

    The owner, 2026-08-17, listing what the radar loader should front: "every
    single time there is that loading state, all I want to see is the radar
    animation ... except, of course, the poster app (because that is a very
    special case, so no loader for that)."

    Why it is special is in this app's own docstring and in `sync_ui.py`'s
    table.  It is opened by a 1500 ms HOLD on the launcher -- the wearer has
    already spent a second and a half deciding -- and it must appear instantly.
    It also already stages its own arrival in four steps, and stage 1 puts the
    WEARER'S NAME at its final size on the panel.  A generic loading screen in
    front of that would replace real information with decoration and would cost
    the pack read, the tile bank and a keyframe to do it.

    THE DURATION IS 1500 ms IN EVERY SENTENCE HERE, INCLUDING THE FAILURE
    MESSAGES.  `HOLD_MS` was 2000 until the owner's 2026-08-16 feel adjustment
    and the prose outlived the constant, so this class described the gesture with
    the old number until 2026-08-24.  Two outside reviews reported it; the first
    fix repaired this docstring and MISSED the message below, because that string
    is SPLIT ACROSS TWO SOURCE LINES between the number and the noun -- so the
    stale phrase was in the assembled message and in no single line of any file,
    and a line-oriented search for it came back clean.
    `scripts/export-source.py`'s `hold-contract-consistent` gate now reads
    `HOLD_MS` out of the exported launcher and refuses any hold duration in any
    exported text that disagrees with it, on prose normalised across line breaks
    and string seams.  It is why this paragraph names the old value as a number
    beside its constant rather than quoting the sentence it replaced.

    The absence was previously implicit: `loading` is simply missing from
    `ALLOWED` above, and nobody wrote down that it must stay missing.  These
    three tests are that record, and they fail loudly enough to send whoever
    trips them back to this docstring.
    """

    #: Every name that would put the loading screen in front of this app.
    LOADER = ("loading", "loading_radar")

    def test_the_entry_file_never_starts_a_loading_screen(self):
        for name, line in imports_of(TREE):
            self.assertNotIn(
                name, self.LOADER,
                "line %d imports %s: the poster is opened by a 1500 ms hold "
                "and must appear instantly -- see this class's docstring"
                % (line, name))
        self.assertNotIn("loading.begin", SOURCE)

    def test_no_file_in_the_app_starts_one_either(self):
        """`__init__.py` is not the only door.  A `loading.begin` anywhere
        under the app -- in `badge_state`, in a vendored copy someone edited --
        would put the screen up just the same."""
        for path in sorted(APP.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if (isinstance(function, ast.Attribute)
                        and function.attr == "begin"
                        and getattr(function.value, "id", None) == "loading"):
                    self.fail("%s:%d calls loading.begin()"
                              % (path.relative_to(REPO), node.lineno))

    @requires_repository
    def test_the_loader_is_not_vendored_into_this_app(self):
        """Two guards, because either one alone can be worked around.

        `scripts/sync_ui.py` must not list a poster path as a consumer -- that
        is what would COPY the module in on the next sync -- and no such file
        may exist on disk, which is what would let a hand-dropped copy be
        imported before anyone ran the script.
        """
        table = ProvenanceTests().table()
        here = str(APP.relative_to(REPO))
        for canonical, consumers in table:
            if pathlib.Path(canonical).stem not in self.LOADER:
                continue
            for relative in consumers:
                self.assertFalse(
                    relative.startswith(here + "/"),
                    "sync_ui.py vendors %s into the poster app" % canonical)
        for name in self.LOADER:
            self.assertFalse((APP / (name + ".py")).exists(),
                             "%s.py appeared in the poster app" % name)


class FootprintTests(unittest.TestCase):
    """Counts, not milliseconds: what the launch path parses, and what the
    flash carries. Both transfer between machines; neither is a device timing
    claim."""

    def bytes_of(self, *names):
        return sum((APP / name).stat().st_size for name in names)

    # THE SOURCE CEILING IS A SMELL CHECK AND NOT THE REAL GATE, and it was
    # 14 KB until 2026-08-21, when it stopped a functional change with 95 bytes
    # of headroom and the measurement below showed it had been guarding the
    # wrong number all along.
    #
    # WHAT THE DEVICE PAYS.  The badge runs COMPILED BYTECODE (`AGENTS.md`), and
    # `scripts/build_mpy.py` invokes mpy-cross with no `-O`, which strips
    # comments AND docstrings anyway: this file measured 15,319 B of source and
    # 2,171 B of `.mpy`, against 14,241 and 2,047 before the backdrop cache was
    # armed. So a page of prose costs the arrival NOTHING and a line of code
    # costs it 124 bytes. The compiled assertion below is the one that can see
    # that difference; this one only catches a file growing a whole new
    # RESPONSIBILITY.
    #
    # 18 KB is `badgecard`'s own entry cap
    # (`badgecard/tests/test_card_purity.py::EntryFootprintTests.CAP`), so the
    # two seams are held to one number instead of two.
    #
    # RAISED FROM 16 KB ON 2026-08-23 WITH A MEASUREMENT, not a shrug. The idle
    # seam put an `idle.Panel` in both entry files; this one's SOURCE went
    # 15,319 -> 16,275 B, past the old cap, while its BYTECODE -- the thing the
    # badge loads -- went 2,242 -> 2,330 B against `MPY_CAP`'s 4,096. So 88 of
    # the 956 bytes are code and the rest is prose, and `mpy-cross` discards
    # prose entirely. A source cap that tight was about to force the reasoning
    # for a load-bearing behaviour out of the file that implements it, in the
    # name of a stall it cannot measure. `MPY_CAP` is untouched and is the gate
    # that actually describes the device.
    #
    # RAISED AGAIN ON 2026-08-26, same discipline, same shape of number. The
    # BadgeLink placement opt-in (owner ruling #22) took SOURCE 17,596 -> 20,278 B
    # and BYTECODE 2,311 -> 2,558 B against `MPY_CAP`'s 4,096 -- so 247 of the
    # 2,682 bytes are code and the other 2,435 are the reasoning for why the
    # poster of all apps has to opt in: it is the product's RESTING state
    # (`launcher/menu/idle.py` returns it after 30 s), so an app that never calls
    # `set_active(True)` silently withholds every connect moment after the first
    # ~13 seconds of a boot. That was measured on hardware as a 12.7-second
    # doorbell window followed by 449 seconds of silence, and it is exactly the
    # kind of load-bearing WHY a tight source cap would push out of the file that
    # implements it. `MPY_CAP` is still untouched and still 60% clear.
    # RAISED ONCE MORE ON 2026-08-26, and this time the code delta is ZERO. The
    # roster's CAPACITY cost took source 20,278 -> 22,753 B and BYTECODE 2,541 ->
    # 2,541 B: every one of those 2,475 bytes is prose. What it records is that
    # the opt-in above is a capacity control as well as a reachability one and
    # that only the reachability half was ever argued -- the poster is
    # join-allowed and is where an untouched badge spends its day, every app exit
    # is a `machine.reset()` landing the wearer at the join-allowed launcher, so
    # no ordinary wearer state withholds and `BOOT_JITTER_MS` spaces a herd
    # rather than a rate. That belongs next to the opt-in, because the reader who
    # needs it is the one adding a fifth app to the roster.
    #
    # MEASURED, NOT ASSUMED, and stated precisely so nobody reads it as stronger
    # than it is: the two `.mpy` files are the same SIZE and are not byte-equal.
    # Comments shift the line numbers of the code below them, and the line-number
    # table is part of the module -- so "identical size, different bytes" is the
    # expected signature of a comment-only edit, and a byte-equality claim here
    # would be false.
    SOURCE_CAP = 23 * 1024
    MPY_CAP = 4 * 1024

    def test_the_entry_file_stays_small(self):
        """Weight belongs in the modules imported after stage 0, not here."""
        self.assertLess(ENTRY.stat().st_size, self.SOURCE_CAP,
                        "the entry file grew a new responsibility")

    def test_the_compiled_entry_module_stays_small(self):
        """THE GATE THAT MATCHES THE DEVICE: bytecode, not source.

        Skipped rather than failed without the pinned toolchain, because the
        fast lane's promise is `python3 -m unittest` on a bare checkout and this
        is the one assertion here that needs mpy-cross. The production lane
        (`playground/scripts/production-lane.sh`) always has it.
        """
        cross = pathlib.Path(
            os.path.expanduser("~/.cache/badge-playground/micropython/"
                               "mpy-cross/build/mpy-cross"))
        toolchain = os.environ.get("BADGE_PLAYGROUND_TOOLCHAIN")
        if toolchain:
            cross = pathlib.Path(toolchain) / "micropython/mpy-cross/build/mpy-cross"
        if not cross.exists():
            self.skipTest("mpy-cross is not built at %s" % cross)
        out = pathlib.Path(tempfile.mkdtemp()) / "poster.mpy"
        result = subprocess.run([str(cross), "-o", str(out), str(ENTRY)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(out.stat().st_size, self.MPY_CAP,
                        "the entry module the badge actually loads is %d B"
                        % out.stat().st_size)

    def test_the_first_two_stages_parse_a_fraction_of_the_editor(self):
        """Stage 1 -- the wearer's name, on screen -- reaches these files and
        no others. `identity_view` alone imports 472,936 B across ten modules
        before it can draw the same line."""
        # `backlight.py` joined on 2026-08-23: `badge_state` imports it at
        # module scope and the entry file imports it between stages, so listing
        # it is honesty rather than pedantry -- the figure is what the LAUNCH
        # PATH parses, and it is on it.
        #
        # THE BOUND WENT 160 KB -> 192 KB when `idle.py` was here too, and the
        # SOURCE figure is why that was a smell check rather than a cost: the two
        # of them were 19,589 B of source compiling to 1,457 B of bytecode
        # (522 + 935, mpy-cross with no `-O`), because both were mostly the
        # reasoning for a 30-second threshold. The badge runs the bytecode. The
        # 2026-08-24 ruling took `idle.py` out of this app entirely, so ~10 KB of
        # that bound is now unused headroom rather than a second file; the bound
        # is deliberately not lowered to match, because it is a smell check on
        # stage 1's CLAIM and not a budget.
        stage_one = self.bytes_of("__init__.py", "badge_state.py", "poster.py",
                                  "ui.py", "identity_catalogue.py",
                                  "identity_faces.py", "backlight.py")
        self.assertLess(stage_one, 192 * 1024)
        # The artwork module stage 2 imports is bigger than everything stage 1
        # touched, which is the entire argument for the staging.
        self.assertGreater((APP / "skins.py").stat().st_size, stage_one * 0.8)


class IdleTests(unittest.TestCase):
    """THE POSTER NEVER DIMS, and this class is the absence made checkable.

    **Owner ruling, 2026-08-24, verbatim: *"The poster app currently dims after
    a timeout. Poster should never dim"*.** This app had a full `idle.Panel`
    between 2026-08-23 and that ruling -- dim at 30 s, `poster_ms=None` for "it
    IS the destination, so it dims and stays" -- and the ruling deleted the
    whole seam rather than moving its threshold.

    WHY THE ABSENCE NEEDS FOUR ASSERTIONS RATHER THAN NONE. Nothing in the
    PICTURE can show it: a dim is `display.backlight`, which moves the panel's
    brightness and not one byte of the framebuffer, so no rendered-output test
    in this suite or in the browser lane could ever see the seam come back.
    The 2026-08-24 device session recorded the same limit from the other side --
    the dim emits nothing on serial either, so its only signature is its own
    failure. An AST walk is therefore the ONLY instrument that can hold this
    ruling, which is why it walks for the import, the class, the frame poll and
    the vendored file separately: a partial revert would leave the app dimming
    again with every other gate green.

    What stays asserted is what did not change: the wearer's brightness still
    reaches the panel exactly once, and this app still never sleeps the badge.
    """

    def entry(self):
        return ENTRY.read_text()

    def update_body(self):
        for node in TREE.body:
            if isinstance(node, ast.FunctionDef) and node.name == "update":
                return node
        self.fail("the entry file no longer defines update()")

    def call_named(self, tree, attr):
        return [node for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == attr]

    def test_there_is_no_idle_clock_in_this_app_at_all(self):
        """No `idle.Panel`, no `idle.Idle`, nothing. The ruling is total."""
        for attr in ("Panel", "Idle"):
            self.assertEqual([], self.call_named(TREE, attr),
                             "the poster built an idle clock again; the owner "
                             "ruled on 2026-08-24 that it never dims")

    def test_the_app_does_not_import_idle(self):
        """Belt and braces on the call walk, and it catches a HALF revert.

        An `import idle` with no `Panel` yet is somebody mid-way through putting
        the dim back, which is the state this suite most wants to fail in.
        """
        for node in ast.walk(TREE):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, "idle")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "idle")

    def test_the_vendored_clock_is_gone_from_this_app(self):
        """And `scripts/sync_ui.py` no longer copies one here.

        A file left behind would be ~10 KB of flash the app never imports, and
        the next reader would reasonably assume the seam still exists.
        """
        self.assertFalse((APP / "idle.py").exists(),
                         "poster/badge/poster/idle.py is back; sync_ui.py's "
                         "idle row must not list this app")

    def test_no_frame_of_this_app_polls_an_idle_clock(self):
        body = self.update_body()
        polls = [node for node in ast.walk(body)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "frame"]
        self.assertEqual([], polls, "the frame loop polls an idle clock again")

    def test_the_wearers_brightness_is_written_once_outside_the_frame_loop(self):
        """The one thing the removed seam was also doing, and it still happens.

        `panel.restore()` used to be the write. It is a direct `_light(...)` now,
        and it must stay OUT of `update()`: the panel is hardware and this value
        never moves while the app is open.
        """
        self.assertIn('_light(state["brightness"])', self.entry())
        body = self.update_body()
        for node in ast.walk(body):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotEqual(node.func.id, "_light",
                                    "the brightness write moved into the frame")

    def test_nothing_here_names_the_dim_stop(self):
        """`backlight.IDLE_PERCENT` is the DIM level and this app has no dim.

        It is still a legitimate constant for the launcher and `badgecard`; a
        reference appearing HERE means the seam came back by another name.
        """
        self.assertNotIn("IDLE_PERCENT", self.entry())

    def test_the_app_never_sleeps_the_badge(self):
        """The owner's part (3), over every module this app carries.

        There is NO auto-sleep, ever: the automatic path always returns to the
        badge and never to a dark panel. This app is where a "the wearer has
        clearly gone home" rung would be most tempting, so the absence is
        asserted rather than assumed.
        """
        for path in app_modules():
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotEqual(node.func.attr, "sleep", path.name)

    def test_the_brightness_ladder_is_the_shared_one(self):
        """Vendored, not written here, so the launcher and the badge agree.

        `scripts/sync_ui.py --check` is the real gate; this one names the reason
        in the suite that would otherwise look like the file's owner. `idle.py`
        was in this list until the 2026-08-24 ruling and is not vendored here at
        all now -- `test_the_vendored_clock_is_gone_from_this_app` is its
        replacement.
        """
        shared = REPO / "shared"
        for name in ("backlight.py",):
            self.assertEqual((APP / name).read_bytes(),
                             (shared / name).read_bytes(),
                             "%s has drifted; run scripts/sync_ui.py" % name)


if __name__ == "__main__":
    unittest.main()
