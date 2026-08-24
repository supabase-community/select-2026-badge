"""The badge app's reader agrees with the editor's repairer, or it is wrong.

THIS IS THE INVARIANT THE WHOLE APP RESTS ON, and it is the one place the
design deliberately does NOT reuse identity's code.  `identity_model.repair` is
48,490 bytes of schema, migration, enum tables and `json` to answer six
questions about six fields, and a worn badge would parse all of it before it
could draw a name.  `badge_state` answers those six questions in 190 lines.

The risk that buys is schema drift: two readers of one file, agreeing today.
So this suite converts the risk into a gate rather than accepting it.

*   EVERY STATE THE EDITOR CAN WRITE.  `repair` is total and its output is the
    only shape that ever reaches the disk, so for any input at all the two
    readers must agree about `repair`'s OUTPUT -- name, line2, face,
    background, stickers, brightness, motion.  That is checked over a corpus
    that includes the editor's own defaults, a full badge, hostile junk and
    every field individually broken.
*   EVERY DEFAULT.  Six literals in `badge_state` shadow six in
    `identity_model`; each is compared to its source here, so adding a
    background default or moving `NAME_MAX` fails this suite rather than
    shipping a badge that draws a different string from the editor.
*   TOTALITY.  Nothing raises, whatever the file says, because an exception on
    this path reaches `badgeware.fatal_error` -- a modal that blocks the badge
    until a keypress and then resets it.

WHERE THEY ARE ALLOWED TO DIFFER, stated so the difference is a decision and
not a surprise: `repair` COERCES a wrong-typed field ("80" becomes 80, 7
becomes the name "7", a mark with an unreadable coordinate is parked at the
centre of the canvas), and the reader takes the default or drops the mark
instead. That is only reachable from a hand-edited file, and the test below
pins the direction of the difference so it stays deliberate.
"""

import json
import os
import tempfile
import unittest

import poster_harness  # noqa: F401 - import for its side effect on sys.path
from poster_harness import requires_repository

import badge_state

# `identity_model` IS THE ARCHIVED EDITOR'S SCHEMA and it is the other half of
# every pin in this file: the point is that two independent readers agree.  It is
# not part of the product, so the source export omits it -- and this import used
# to be unconditional, which meant the whole module failed COLLECTION from the
# export rather than telling anybody why.  Guarded, with the cases that need it
# marked, so the export runs everything that is about the shipping app.
if poster_harness.IDENTITY is not None:
    import identity_model as model
else:
    model = None


PICTURE_KEYS = ("name", "line2", "face", "background", "stickers",
                "brightness", "motion")


def picture(state):
    """Just the fields the poster draws, from either reader's output."""
    return {key: state[key] for key in PICTURE_KEYS}


# Inputs chosen so every arm of both readers runs. The junk half matters more
# than the tidy half: `repair` exists because a badge's file can be anything.
CORPUS = (
    ("defaults", {}),
    ("full", {
        "schema": 1, "name": "SAM MEECH", "line2": "SUPABASE",
        "face": "badgewaremax", "background": "glyph.radar",
        "stickers": [{"kind": "github", "x": 0.12, "y": 0.61},
                     {"kind": "heart", "x": 0.9, "y": 0.05}],
        "brightness": 60, "motion": False,
        "home": {"on": True, "motion": "slow", "finish": "vivid",
                 "show_name": True, "show_stickers": False, "recipe": 4},
    }),
    ("long name", {"name": "WWWWWWWWWWWWWWWWWWWW",
                   "line2": "X" * 40}),
    ("padded ids", {"face": "  sins  ", "background": " skin.riso "}),
    ("empty ids", {"face": "", "background": "   "}),
    ("unknown ids", {"face": "notaface", "background": "skin.nope"}),
    ("brightness low", {"brightness": 0}),
    ("brightness high", {"brightness": 9999}),
    ("no stickers key", {"name": "A"}),
    ("stickers not a list", {"stickers": {"kind": "github"}}),
    ("stickers junk items", {"stickers": [None, 3, "github", []]}),
    ("stickers no kind", {"stickers": [{"x": 0.5, "y": 0.5}]}),
    ("stickers over the cap", {"stickers": [{"kind": "star", "x": 0.5,
                                             "y": 0.5}] * 40}),
    ("stickers at the edges", {"stickers": [{"kind": "star", "x": 0.0,
                                             "y": 1.0}]}),
    ("motion string", {"motion": True}),
    ("extra keys", {"name": "A", "future": {"deep": [1, 2, 3]}}),
    ("null everywhere", {"name": None, "line2": None, "face": None,
                         "background": None, "stickers": None,
                         "brightness": None, "motion": None}),
)


@requires_repository
class AgreementTests(unittest.TestCase):
    """`badge_state.coerce(repair(x)) == picture(repair(x))` for every x.

    Read it as: whatever the editor wrote, the badge app draws the same badge.
    The round trip goes through JSON because that is what is actually on the
    disk, and a difference the encoder introduces would be as real as one the
    reader introduced.
    """

    def test_the_two_readers_agree_on_everything_the_editor_writes(self):
        for label, raw in CORPUS:
            repaired = model.repair(raw)
            on_disk = json.loads(json.dumps(repaired))
            self.assertEqual(picture(badge_state.coerce(on_disk)),
                             picture(repaired),
                             "%s: the badge app would draw a different badge "
                             "from the one identity saved" % label)

    def test_a_repaired_state_survives_a_second_pass(self):
        """The reader is idempotent on its own output, like `repair` is."""
        for label, raw in CORPUS:
            once = badge_state.coerce(model.repair(raw))
            self.assertEqual(picture(badge_state.coerce(once)), picture(once),
                             label)


class DefaultTests(unittest.TestCase):
    """Five literals shadow five of identity's. Each is pinned to its source.

    IT WAS SIX UNTIL 2026-08-23. Brightness stopped being a literal here when
    `shared/backlight.py` became the ladder's one home: `DEFAULT_BRIGHTNESS`,
    `BRIGHTNESS_MIN` and `BRIGHTNESS_MAX` were a verbatim duplicate of
    `identity_model`'s -- the drift hazard `docs/design/idle-and-off.md` §3.3
    named -- and the idle dim needed a third reader. The pinning did not
    weaken: the three assertions below still compare this app's numbers against
    the archived schema's, they just reach them through `backlight`.
    """

    @requires_repository
    def test_every_default_matches_the_schema(self):
        fresh = model.new_state()
        self.assertEqual(badge_state.DEFAULT_NAME, fresh["name"])
        self.assertEqual(badge_state.DEFAULT_LINE2, fresh["line2"])
        self.assertEqual(badge_state.DEFAULT_FACE, fresh["face"])
        self.assertEqual(badge_state.DEFAULT_BACKGROUND, fresh["background"])
        self.assertEqual(badge_state.backlight.DEFAULT, fresh["brightness"])
        self.assertEqual(badge_state.DEFAULT_MOTION, fresh["motion"])

    @requires_repository
    def test_every_bound_matches_the_schema(self):
        self.assertEqual(badge_state.NAME_MAX, model.NAME_MAX)
        self.assertEqual(badge_state.LINE2_MAX, model.LINE2_MAX)
        self.assertEqual(badge_state.ID_MAX, model.ID_MAX)
        self.assertEqual(badge_state.MAX_STICKERS, model.MAX_STICKERS)
        self.assertEqual(badge_state.backlight.MIN, model.BRIGHTNESS_MIN)
        self.assertEqual(badge_state.backlight.MAX, model.BRIGHTNESS_MAX)
        self.assertEqual(badge_state.STICKER_SCAN_MAX, model.STICKER_SCAN_MAX)

    @requires_repository
    def test_the_shared_ladder_is_the_archived_schemas_ladder(self):
        """The whole ladder, not only its ends.

        `shared/backlight.py` says in its docstring that it lifted
        `identity_model`'s five levels and five names verbatim; this is what
        makes that a fact rather than a claim, for as long as the archived app
        is still in the tree.
        """
        self.assertEqual(badge_state.backlight.LEVELS, model.BRIGHTNESS_LEVELS)
        self.assertEqual(badge_state.backlight.NAMES, model.BRIGHTNESS_NAMES)

    def test_the_default_state_is_a_fresh_dict_every_call(self):
        first = badge_state.defaults()
        first["stickers"].append({"kind": "x", "x": 0.5, "y": 0.5})
        self.assertEqual(badge_state.defaults()["stickers"], [])

    def test_the_default_state_is_the_one_the_poster_can_draw(self):
        """Every key `poster.Poster` reads is present with no file at all."""
        state = badge_state.defaults()
        for key in PICTURE_KEYS:
            self.assertIn(key, state)


class TotalityTests(unittest.TestCase):
    """Nothing here may raise. An exception on this path is a modal and a
    reset, not a log line."""

    HOSTILE = (
        None, True, 3, -1, 3.5, float("nan"), "", "  ", [], (), {},
        [1, 2, 3], {"name": {"nested": True}}, {"stickers": "github"},
        {"stickers": [{"kind": True, "x": "a", "y": None}]},
        {"stickers": [{"kind": "star", "x": float("nan"), "y": 0.5}]},
        {"stickers": [{"kind": "star", "x": float("inf"), "y": 0.5}]},
        {"stickers": [{"kind": "star", "x": True, "y": 0.5}]},
        {"stickers": [{"kind": "star", "x": 10 ** 400, "y": 0.5}]},
        {"stickers": [{"kind": "star", "x": -0.5, "y": 2.0}]},
        {"brightness": "loud"}, {"brightness": True}, {"motion": "sometimes"},
        {"name": 7}, {"name": 10 ** 5000}, {"face": ["sins"]},
        {1: "a", "b": 2},
    )

    def test_coerce_never_raises_and_always_returns_a_badge(self):
        for index, value in enumerate(self.HOSTILE):
            state = badge_state.coerce(value)
            for key in PICTURE_KEYS:
                # Indexed rather than repr'd, and that is not cosmetic: this
                # corpus contains 10**5000, and CPython 3.11 RAISES on
                # `str()` of an integer past 4300 digits. `identity_model`
                # carries the same scar in `_text`, which is why the reader
                # here never converts an int to text at all.
                self.assertIn(key, state, "HOSTILE[%d]" % index)
            self.assertIsInstance(state["name"], str)
            self.assertIsInstance(state["stickers"], list)
            self.assertIsInstance(state["motion"], bool)

    def test_a_mark_that_survives_is_drawable(self):
        """A kept mark has an id and a fraction, or the renderer would fault.

        `mark_origin` multiplies x and y by the canvas, so a string or a NaN
        there is a `TypeError` inside the frame loop -- which is the one place
        this app cannot afford one.
        """
        for value in self.HOSTILE:
            for mark in badge_state.coerce(value)["stickers"]:
                self.assertTrue(mark["kind"])
                self.assertIsInstance(mark["kind"], str)
                for axis in ("x", "y"):
                    self.assertIsInstance(mark[axis], float)
                    self.assertTrue(0.0 <= mark[axis] <= 1.0)

    @requires_repository
    def test_a_hostile_stickers_list_cannot_stall_the_launch(self):
        huge = {"stickers": [{"kind": "star", "x": 0.5, "y": 0.5}] * 100000}
        self.assertEqual(len(badge_state.coerce(huge)["stickers"]),
                         model.MAX_STICKERS)


class ReadTests(unittest.TestCase):
    """The file half, against a real filesystem."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "identity.json")

    def write(self, text):
        with open(self.path, "w") as handle:
            handle.write(text)

    def test_a_missing_file_is_a_default_badge(self):
        state = badge_state.read(os.path.join(self.dir, "nothing.json"))
        self.assertEqual(picture(state), picture(badge_state.defaults()))
        self.assertEqual(badge_state.source, "default")

    def test_a_directory_where_the_file_should_be_is_a_default_badge(self):
        state = badge_state.read(self.dir)
        self.assertEqual(picture(state), picture(badge_state.defaults()))
        self.assertEqual(badge_state.source, "default")

    def test_an_empty_file_is_a_default_badge(self):
        self.write("")
        self.assertEqual(picture(badge_state.read(self.path)),
                         picture(badge_state.defaults()))
        self.assertEqual(badge_state.source, "default")

    def test_a_truncated_save_is_a_default_badge(self):
        self.write('{"name": "SAM", "stick')
        self.assertEqual(picture(badge_state.read(self.path)),
                         picture(badge_state.defaults()))
        self.assertEqual(badge_state.source, "default")

    def test_json_that_is_not_an_object_says_so(self):
        self.write('["SAM"]')
        self.assertEqual(picture(badge_state.read(self.path)),
                         picture(badge_state.defaults()))
        self.assertEqual(badge_state.source, "shape")

    @requires_repository
    def test_a_real_save_round_trips(self):
        saved = model.repair({"name": "SAM MEECH", "line2": "SUPABASE",
                              "background": "skin.riso", "brightness": 40,
                              "motion": False,
                              "stickers": [{"kind": "github", "x": 0.2,
                                            "y": 0.8}]})
        self.write(json.dumps(saved))
        self.assertEqual(picture(badge_state.read(self.path)), picture(saved))
        self.assertEqual(badge_state.source, "file")


class SelectTests(unittest.TestCase):
    """Picking the worn badge out of a five-slot store.

    The step `read` gained on 2026-08-17 when the launcher's hold was retargeted
    from `identity` to `badgecard`.  It runs BEFORE `coerce`, so everything the
    agreement suite above pins is untouched: `coerce` still receives one flat
    six-field object and still has to answer the same six questions about it.
    """

    def test_the_active_badge_is_the_one_that_is_drawn(self):
        store = {"schema": 1, "active": 1, "badges": [
            {"name": "FIRST", "background": "skin.oxide"},
            {"name": "WORN", "background": "skin.riso"},
            {"name": "THIRD", "background": "skin.crt"}]}
        state = badge_state.coerce(badge_state.select(store))
        self.assertEqual("WORN", state["name"])
        self.assertEqual("skin.riso", state["background"])

    def test_identitys_older_flat_shape_still_reads(self):
        """A badge whose editor has not been replaced yet keeps working."""
        flat = {"schema": 1, "name": "SAM", "background": "skin.crt"}
        self.assertEqual("SAM",
                         badge_state.coerce(badge_state.select(flat))["name"])

    def test_an_out_of_range_index_falls_back_to_the_first_badge(self):
        for index in (-1, 5, 99, "1", None, 1.0):
            store = {"active": index, "badges": [{"name": "FIRST"},
                                                 {"name": "SECOND"}]}
            self.assertEqual(
                "FIRST",
                badge_state.coerce(badge_state.select(store))["name"])

    def test_true_does_not_select_the_second_badge(self):
        """`True` IS an `int` in Python.  Rejecting `bool` before `int` is the
        same guard the coordinate reader needs, for the same reason."""
        store = {"active": True, "badges": [{"name": "FIRST"},
                                            {"name": "SECOND"}]}
        self.assertEqual("FIRST",
                         badge_state.coerce(badge_state.select(store))["name"])

    def test_a_hostile_store_is_still_a_drawable_badge(self):
        for store in ({"badges": []}, {"badges": "nope"}, {"badges": [None]},
                      {"badges": [7]}, {"badges": {}}, {}, None, [], 3, "x"):
            state = badge_state.coerce(badge_state.select(store))
            self.assertEqual(picture(state), picture(state))
            self.assertIn("background", state)

    def test_a_five_slot_store_round_trips_through_the_real_file(self):
        path = os.path.join(tempfile.mkdtemp(), "badgecard.json")
        with open(path, "w") as handle:
            json.dump({"schema": 1, "active": 2, "badges": [
                {"name": "A", "background": "skin.oxide", "face": "curse",
                 "stickers": []},
                {"name": "B", "background": "skin.crt", "face": "curse",
                 "stickers": []},
                {"name": "SAM MEECH", "background": "glyph.radar",
                 "face": "badgewaremax",
                 "stickers": [{"kind": "github", "x": 0.2, "y": 0.8}]}]},
                handle)
        state = badge_state.read(path)
        self.assertEqual("file", badge_state.source)
        self.assertEqual("SAM MEECH", state["name"])
        self.assertEqual("glyph.radar", state["background"])
        self.assertEqual(1, len(state["stickers"]))


class DeviceFieldTests(unittest.TestCase):
    """Brightness is a property of the PANEL, so it lives at the store's root.

    Before 2026-08-23 `coerce` read `brightness` out of whatever `select`
    returned, and for a multi-badge store that is a BADGE -- so the format
    actually described a per-badge brightness that no editor could write and
    that would have changed the screen every time the wearer switched badges.
    `badgecard`'s BRIGHTNESS row writes the root; these are the reader's half.
    """

    def store(self, root=None, badge=None):
        state = {"schema": 1, "active": 0,
                 "badges": [dict(badge or {}, name="SAM")]}
        state.update(root or {})
        return state

    def test_the_roots_brightness_reaches_the_selected_badge(self):
        picked = badge_state.select(self.store({"brightness": 40}))
        self.assertEqual(picked["brightness"], 40)
        self.assertEqual(badge_state.coerce(picked)["brightness"], 40)

    def test_it_is_the_same_for_every_badge_in_the_store(self):
        state = {"schema": 1, "brightness": 40, "active": 0,
                 "badges": [{"name": "ONE"}, {"name": "TWO"}]}
        for index in (0, 1):
            state["active"] = index
            picked = badge_state.coerce(badge_state.select(state))
            self.assertEqual(picked["brightness"], 40, index)

    def test_a_store_with_no_brightness_is_the_factory_level(self):
        picked = badge_state.coerce(badge_state.select(self.store()))
        self.assertEqual(picked["brightness"], badge_state.backlight.DEFAULT)

    def test_the_root_wins_over_a_badge_local_value(self):
        """CORRECTED 2026-08-23, and the old behaviour was a trap.

        This asserted the BADGE's value won, on the theory that a hand-edited
        file is the wearer's file. But `card_model.repair_badge` deliberately
        CARRIES unknown keys, so a badge that once held a `brightness` keeps it
        through every save and load -- permanently masking the root, which is the
        only place `badgecard`'s BRIGHTNESS row writes. The wearer would have had
        a brightness control with no effect and no way to find out why.
        """
        picked = badge_state.select(
            self.store({"brightness": 40}, {"brightness": 100}))
        self.assertEqual(picked["brightness"], 40)

    def test_an_unusable_badge_does_not_cost_the_panel_its_level(self):
        # A device field outlives a badge by definition: `select` returned a bare
        # `{}` here until 2026-08-23, so one broken badge in the store also
        # threw away the wearer's brightness.
        picked = badge_state.coerce(badge_state.select(
            {"schema": 1, "active": 0, "badges": [None], "brightness": 40}))
        self.assertEqual(picked["brightness"], 40)

    def test_a_float_reads_the_same_here_as_in_the_launcher_and_the_editor(self):
        """The drift that would have shown up as a JUMP across the handoff.

        This reader gated on `isinstance(..., int)` before clamping, so a store
        holding 55.5 gave the launcher and the editor 55 and gave this app the
        factory 80 -- and the wearer would have watched the panel change
        brightness on the 45-second trip to the badge.
        """
        picked = badge_state.coerce(badge_state.select(
            self.store({"brightness": 55.5})))
        self.assertEqual(picked["brightness"], 55)
        self.assertIsInstance(picked["brightness"], int)

    def test_the_flat_identity_shape_still_works_untouched(self):
        flat = {"name": "SAM", "brightness": 40, "motion": False}
        self.assertIs(badge_state.select(flat), flat)
        self.assertEqual(badge_state.coerce(badge_state.select(flat))["brightness"], 40)

    def test_the_carry_never_mutates_the_parsed_store(self):
        # This module is read-only by ruling and by test; writing into the
        # parsed store would be a write.
        state = self.store({"brightness": 40})
        badge_state.select(state)
        self.assertEqual(state["badges"][0], {"name": "SAM"})

    def test_nothing_but_brightness_is_a_device_field(self):
        # A second entry here would be a second thing that stops being per-badge,
        # which is a schema decision and not a tidy-up.
        self.assertEqual(badge_state.DEVICE_KEYS, ("brightness",))

    def test_an_out_of_range_root_brightness_is_clamped(self):
        for raw, expected in ((0, 20), (-5, 20), (400, 100)):
            picked = badge_state.coerce(
                badge_state.select(self.store({"brightness": raw})))
            self.assertEqual(picked["brightness"], expected, raw)

    def test_a_root_brightness_of_the_wrong_type_is_the_factory_level(self):
        for raw in ("80", True, None, [80], {}):
            picked = badge_state.coerce(
                badge_state.select(self.store({"brightness": raw})))
            self.assertEqual(picked["brightness"],
                             badge_state.backlight.DEFAULT, repr(raw))

    def test_a_hostile_store_still_returns_a_drawable_badge(self):
        for value in (None, [], "badge", 7, {"badges": "nope"},
                      {"badges": []}, {"badges": [None]},
                      {"badges": [{}], "active": True}):
            picked = badge_state.coerce(badge_state.select(value))
            self.assertIn("brightness", picked)


if __name__ == "__main__":
    unittest.main()
