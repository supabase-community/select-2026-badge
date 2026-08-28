"""The shared setup state contract (Card FT-B).

BadgeLink's ``set_name`` and ``set_skin`` appliers have to write the file
``setup`` reads at open. This module is the ONLY place either side's shape is
spelled, and it exists for the same reason ``rpc_contract`` exists: two files
authored the same format independently once already (``identity_store`` and
``card_store``), and the drift is silent -- a badge that loads a state written by
a stranger shows a factory badge instead of the wearer's.

WHO OWNS WHAT, because "shared" is not the same as "joint":

* **``setup`` OWNS the on-disk format.** ``card_model.SCHEMA``,
  ``card_store.STATE_PATH`` and ``card_model.repair`` are canonical. This module
  is a WRITER that agrees with them, never a second definition of them.
* **This module owns the write.** The applier never opens setup's file and
  never spells one of its keys; it calls :func:`set_name` / :func:`set_skin`.
* **Nothing here reaches into the other side's literals at runtime.**
  ``badgelink/tests/test_setup_state.py`` imports the real
  ``setup.card_model``/``card_store`` and pins every value below against it,
  so a setup-side change fails a test instead of a badge.

WHY THIS MODULE DOES NOT IMPORT ``card_model`` AND ``setup`` DOES NOT IMPORT
THIS ONE. Both directions were considered and both are rejected by evidence
already in the tree:

* Importing ``card_model`` here would put 23 KB of app code plus the generated
  ``card_faces`` table on the ``/system/lib`` boot path, and ``card_model``
  imports ``card_faces`` at module scope. A boot-path module may not depend on an
  app tree.
* Making ``setup`` import THIS would give the app that ships a hard
  dependency on ``/system/lib``. ``network_runtime`` already records the rule
  verbatim for ``pushlink``'s literals: "a module-scope import of a file a
  half-refreshed ``/system/lib`` might not carry would take the boot down", and
  an import that raises inside ``launch()`` resets the badge. ``setup`` is
  the app that ships. It keeps zero new dependencies and a test carries the
  agreement, which is the same trade ``network_runtime`` made.

MINIMAL KNOWLEDGE, MAXIMAL CARRY. The writer parses the file, changes ONE key on
the ACTIVE badge and writes every other byte back verbatim. It does not repair,
normalise, migrate, reorder or drop anything it does not recognise, because
``card_model.repair`` is total and idempotent and is what runs at open. So a
badge configured by a NEWER setup survives a remote name change with its new
fields intact -- the same carry rule ``repair_badge`` implements, honoured by not
having an opinion.

IT REFUSES RATHER THAN OVERWRITE, and that is the one non-obvious rule.
``card_store.load`` falls back to ``<path>.bak`` when the primary is corrupt or
missing. A writer that answered a corrupt primary by writing a fresh minimal
state would make setup load THAT and never consult the backup, so a remote
name change would silently destroy up to five saved badges. So: a corrupt
primary raises, and a MISSING primary raises when a backup exists. Only "no
primary and no backup" -- a badge whose setup has never been opened -- gets a
fresh file.

MicroPython surface only: ``json`` and ``os``, no ``re``, no f-strings, no
``typing``. The write is temp -> flush -> os.sync -> rename, which is the only
sequence that survives power loss on LittleFS, and it never refreshes the
``.bak`` milestone: a milestone is a wearer COMMIT (badge-button rule B6) and a
command from a web page is not one.
"""

import json
import os


# ---------------------------------------------------------------------------
# setup's literals.  Every one of these is PINNED against the real module by
# badgelink/tests/test_setup_state.py.  Do not change one here to make a test
# pass; change setup and let the pin tell you.
# ---------------------------------------------------------------------------

STATE_PATH = "/state/badgecard.json"      # card_store.STATE_PATH
BACKUP_SUFFIX = ".bak"                    # card_store.BACKUP_SUFFIX
SCHEMA = 1                                # card_model.SCHEMA
NAME_MAX = 12                             # card_model.NAME_MAX
# `card_model.CARRY_BADGES`, and it was `MAX_BADGES` until 2026-08-24, when the
# owner removed setup's five save slots. The NUMBER did not move and its
# MEANING did: it was "how many badges a wearer keeps" and it is now "how many
# legacy slot entries survive a load", because setup draws exactly one card
# and the list is only still a list because four apps -- this one included --
# spell the format that way. Nothing in this module clamps on it either way; see
# `_active_badge`, which clamps on `len(badges)` and says why.
CARRY_BADGES = 5                          # card_model.CARRY_BADGES
DEFAULT_NAME = ""                         # card_model.DEFAULT_NAME
# A LITERAL, WHERE `card_model`'s IS `catalogue.ENTRIES[0][0]` SINCE 2026-08-26.
# This module is the WIRE CONTRACT's mirror of setup's state file, so its
# defaults are part of what a remote caller is promised, and a promise that
# changes meaning without changing text is worse than a duplicated string. It
# did not follow the editor into a derivation for that reason and for one more:
# two derived defaults re-point in agreement when the artwork is reordered, which
# `test_scalars_match_card_model` cannot see -- that asks whether the two agree,
# not what they agree ON. `test_the_contract_mirrors_the_editors_defaults` pins
# this against the TABLE instead.
DEFAULT_BACKGROUND = "glyph.ring-buffer"  # card_model.DEFAULT_BACKGROUND

KEY_SCHEMA = "schema"
KEY_ACTIVE = "active"
KEY_BADGES = "badges"
KEY_HOME = "home"
KEY_NAME = "name"
KEY_BACKGROUND = "background"

# NOT WRITTEN, DELIBERATELY, and this is the whole reason the applier needs no
# copy of the 108-row face table.  `card_model.repair_badge` recomputes `face`
# from `background` on every load and discards whatever the file carried -- the
# owner's 2026-08-17 ruling is that the skin dictates the face.  A writer that
# set it would be asserting a rule setup does not have; a writer that leaves
# it stale is corrected at open, for free.
KEY_FACE = "face"

# `card_model._ident`'s bound, for a background id.
SKIN_ID_MAX = 48

# The two id namespaces the catalogue uses (`skin.` for the procedural skins,
# `glyph.` for the decks).  THE COUNTS ARE DELIBERATELY NOT STATED HERE: they
# were 88 and 18, are 26 and 12 since the owner's 2026-08-27 cut, and this
# module does not care -- see SHAPE ONLY below, which is the actual contract.
# SHAPE ONLY: an id this build has never heard of is
# ACCEPTED and stored, because `card_faces.FALLBACK_FACE` already records the
# rule -- "an unknown id keeps its string in state so reinstalling the asset
# restores the badge".  The owner is still finalizing the catalogue (Card FT-S
# authored NO skins table for exactly that reason), so a badge that rejected an
# id its firmware predates would reject the catalogue's own future.
SKIN_PREFIXES = ("skin.", "glyph.")


# ---------------------------------------------------------------------------
# the live-refresh hook: PRESENT, FLAGGED OFF, BEHIND THE BATTERY GATE
# ---------------------------------------------------------------------------

# THE OWNER'S 2026-08-22 RULING is instant-update-BEHIND-THE-BATTERY-GATE:
# next-open semantics ship now and a live wearer-card refresh is a flagged hook.
# The flag is here rather than in the applier because the COST is here.
#
# WHAT IT WOULD COST, in numbers this repository already measured rather than a
# worry. A live refresh means a running setup re-reads this file and rebuilds
# its artwork mid-session. Stage 2 artwork is 63.752 ms median and 247.900 ms max
# at HIRES with two skins over the 180 ms settle, and at HIRES the name goes
# through `shared/nametag.plated`, so the frame carrying it also pays a COLD
# nick-plate build -- 175-750 us plus a 57-75 KB transparent buffer
# (`setup/host/name_cost.mjs`). Every one of those figures was measured for a
# refresh the WEARER asked for, at a moment the panel was already changing. A
# remote command can arrive at any frame, and the panel/CPU/current cost of an
# unrequested full repaint at an arbitrary moment has never been measured against
# the battery budget. `AGENTS.md` forbids starting a battery workload without an
# owner-announced away window, so the measurement cannot be taken here.
#
# TURNING IT ON is one flag plus the setup-side reader, and the reader is
# NOT in this card's scope. Do not flip this without the battery number.
LIVE_REFRESH_ENABLED = False

# Where the hook would drop its note. A note rather than a callback: the writer
# runs in `/system/main.py`'s frame pump and setup runs in `launch()`, so
# there is no object either side can hold. Deliberately a SEPARATE file from the
# state, so a setup that has never heard of it is unaffected by its presence.
LIVE_REFRESH_PATH = "/state/badgecard-refresh.json"


class StateError(Exception):
    """The write could not be performed. The applier turns this into a failed ack."""


# ---------------------------------------------------------------------------
# validation -- MIRRORS THE DB CHECKS EXACTLY.  The constraint is the boundary;
# this is the courtesy, so a badge that disagrees with the constraint is a bug.
# ---------------------------------------------------------------------------

# `badge_commands_set_name_payload_check`'s `translate(...)` charset, character
# for character, from badgelink/supabase/schemas/badgelink.sql. It is the
# MEASURED nonzero-ink intersection of the ROM faces, which is why it is a
# literal set and not a range test. Spelled as one string so the pin test can
# diff it against the SQL.
NAME_CHARS = (
    " !\"#$%&'()*+,-./0123456789:;<=>?@"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
    "abcdefghijklmnopqrstuvwxyz{|}~"
    "¡¢£©«®°·»¿"
    "ÀÁÂÃÄÅÆÇÈÉ"
    "ÊËÌÍÎÏÐÑÒÓ"
    "ÔÕÖØÙÚÛÜÝÞ"
    "ßàáâãäåæçè"
    "éêëìíîïðñò"
    "óôõöøùúûüý"
    "þ"
)

# The DB's own bound on the `set_name` payload, which is `badges.display_name`'s
# and NOT `NAME_MAX`. The two differ on purpose and the difference is reported
# rather than rejected -- see `set_name`.
NAME_PAYLOAD_MAX = 64

_NAME_CHARS = frozenset(NAME_CHARS)


def valid_name(value):
    """Exactly ``badge_commands_set_name_payload_check``'s verdict on one name.

    Four clauses, in the constraint's own order: a string, 1..64 characters,
    equal to its own ``btrim``, and every character in the measured set.
    """

    if not isinstance(value, str):
        return False
    if len(value) < 1 or len(value) > NAME_PAYLOAD_MAX:
        return False
    # `btrim` with no second argument strips exactly the ASCII whitespace class
    # Python's `str.strip()` strips for these inputs; the charset above admits no
    # other whitespace, so the two agree on everything that can reach here.
    if value != value.strip():
        return False
    for character in value:
        if character not in _NAME_CHARS:
            return False
    return True


def valid_slug(value):
    """The BARE slug class, which is what the deployed console actually sends.

    ``badgelink/web/src/lib/commands.ts``'s ``buildSetSkin`` is
    ``{skin: "supabase"}`` -- ``/^[a-z0-9][a-z0-9-]{0,63}$/``, no dot -- while
    setup's ids are ``skin.supabase`` and ``glyph.alphabet``. Card FT-S added
    no ``set_skin`` payload CHECK, so the DB accepts either and the badge is the
    whole boundary. :func:`resolve_skin` accepts both forms rather than breaking
    the console that is already deployed; the class is also
    ``badge_state.active_app``'s, so a resolved value can be reported back.
    """

    if not isinstance(value, str):
        return False
    if len(value) < 1 or len(value) > 64:
        return False
    first = value[0]
    if not (("a" <= first <= "z") or ("0" <= first <= "9")):
        return False
    for character in value:
        if not (("a" <= character <= "z") or ("0" <= character <= "9")
                or character == "-"):
            return False
    return True


def resolve_skin(value):
    """One ``set_skin`` payload value -> a storable id, or ``None``.

    TWO ACCEPTED FORMS, and the reason is deployment rather than taste:

    * a FULL catalogue id (``skin.supabase``, ``glyph.alphabet``) is stored as
      given. This is the only form that can name a glyph deck, and
      the deployed ``buildSetSkin`` cannot produce it -- its regex has no dot.
      **That is Card FT-W's delta, not a schema defect**: ``set_skin`` has no
      payload CHECK, so nothing in the database has to change for the console to
      start sending a dotted id.
    * a BARE slug is prefixed ``skin.``, which is correct for every procedural
      skin and is exactly what the deployed console means today.

    The resolved id goes back in the ack, so a console that guessed wrong can see
    what the badge actually stored.
    """

    if valid_skin(value):
        return value
    if valid_slug(value):
        prefixed = SKIN_PREFIXES[0] + value
        # RE-VALIDATED, and it is not belt-and-braces: the console's class allows
        # a TRAILING HYPHEN (it is `badge_state.active_app`'s class) and
        # `valid_skin` does not, so `"trail-"` would otherwise resolve to the
        # unstorable `"skin.trail-"`. The invariant this restores --
        # `resolve_skin(x) is None or valid_skin(resolve_skin(x))` -- is asserted
        # over both classes in test_setup_state.py.
        if valid_skin(prefixed):
            return prefixed
    return None


def valid_skin(value):
    """Whether one background id is storable.

    ``set_skin`` HAS NO PAYLOAD CHECK in the schema -- Card FT-S extended the
    vocabulary with four new verbs and left ``set_skin``'s payload to the generic
    object/4096-byte rules -- so unlike every other applier this one is the whole
    boundary rather than a mirror of one. It is deliberately SHAPE-ONLY (see
    ``SKIN_PREFIXES``): a catalogue membership test would reject the catalogue's
    own future.
    """

    if not isinstance(value, str):
        return False
    if len(value) < 1 or len(value) > SKIN_ID_MAX:
        return False
    if value != value.strip():
        return False
    prefixed = False
    for prefix in SKIN_PREFIXES:
        if value.startswith(prefix) and len(value) > len(prefix):
            prefixed = True
            break
    if not prefixed:
        return False
    tail = value.split(".", 1)[1]
    if tail[0] == "-" or tail[-1] == "-":
        return False
    for character in tail:
        if not (("a" <= character <= "z") or ("0" <= character <= "9")
                or character == "-"):
            return False
    return True


# ---------------------------------------------------------------------------
# the file
# ---------------------------------------------------------------------------

def blank_state():
    """The smallest state ``card_model.repair`` completes into a real one.

    Written only when there is provably nothing to lose (no primary AND no
    backup). Every key setup fills in for itself is left out on purpose: a
    writer that guessed `face` or `stickers` would be a second definition of
    them.
    """

    return {
        KEY_SCHEMA: SCHEMA,
        KEY_ACTIVE: 0,
        KEY_BADGES: [{KEY_NAME: DEFAULT_NAME, KEY_BACKGROUND: DEFAULT_BACKGROUND}],
        KEY_HOME: {"on": False, "recipe": 0},
    }


def _exists(path, open_fn):
    try:
        handle = open_fn(path, "r")
    except OSError:
        return False
    handle.close()
    return True


def read(path=None, open_fn=None):
    """The state to modify, or raise.  NEVER repairs and never falls back.

    Raises :class:`StateError` for a corrupt primary, and for a missing primary
    that has a backup beside it. Both cases are the wearer's five badges sitting
    in ``.bak``, one careless write from gone.
    """

    path = path or STATE_PATH
    open_fn = open_fn or open
    try:
        with open_fn(path, "r") as source:
            raw = source.read()
    except OSError:
        if _exists(path + BACKUP_SUFFIX, open_fn):
            raise StateError("setup state missing but a backup exists")
        return blank_state()
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise StateError("setup state is not JSON")
    if not isinstance(value, dict):
        raise StateError("setup state is not a JSON object")
    return value


def save(state, path=None, open_fn=None, sync_fn=None, rename_fn=None):
    """temp -> flush -> sync -> rename.  The rename is the atom.

    ``card_store._write_atomic``'s sequence, and the ``.bak`` milestone is NOT
    refreshed: a milestone is a wearer commit (B6), and three remote name pushes
    must not become three backup writes on a shared 1 MB volume.
    """

    path = path or STATE_PATH
    open_fn = open_fn or open
    text = json.dumps(state)
    temporary = path + ".tmp"
    with open_fn(temporary, "w") as output:
        output.write(text)
        flush = getattr(output, "flush", None)
        if flush is not None:
            flush()
    sync = sync_fn if sync_fn is not None else getattr(os, "sync", None)
    if sync is not None:
        sync()
    (rename_fn or os.rename)(temporary, path)
    return state


def _active_badge(state):
    """The badge dict a remote command edits, creating one if the file has none.

    ``card_model.active``'s index rules, and nothing else: an out-of-range or
    non-integer index means badge 0, because that is the badge setup will
    draw.

    **CLAMPED ON `len(badges)` AND NOT ON `CARRY_BADGES`, and the difference is the
    carry rule.** A draft also refused an index at or past five, which reads like
    a sensible bound and is a divergence: `card_model.active` clamps only on the
    list length, so for a file written by a NEWER setup with six badges and
    `active == 5` the writer would have edited badge 0 while setup drew badge
    5. That is exactly the forward-compatibility case this module promises to
    honour. Growth is not a risk here either way -- nothing in this function
    appends.
    """

    badges = state.get(KEY_BADGES)
    if not isinstance(badges, list) or not badges:
        badges = [{}]
        state[KEY_BADGES] = badges
    index = state.get(KEY_ACTIVE)
    if not isinstance(index, int) or isinstance(index, bool):
        index = 0
    if index < 0 or index >= len(badges):
        index = 0
    badge = badges[index]
    if not isinstance(badge, dict):
        badge = {}
        badges[index] = badge
    return badge


def set_name(name, path=None, **io):
    """Write one name onto the active badge.  NEXT-OPEN semantics.

    Returns ``{"stored": <what the file now holds>, "truncated": bool}``.

    THE TRUNCATION IS REPORTED, NOT REJECTED. The constraint's bound is 64
    characters -- ``badges.display_name``'s -- and ``card_model.NAME_MAX`` is 12,
    because 12 is what ``nametag`` draws and ``nametag`` is what the launcher's
    hold opens. Rejecting a 20-character name the DB accepted would put the badge
    and the constraint into disagreement, which is the one thing an applier may
    not do; storing 20 characters setup truncates at open would make the
    console say "applied" about a name the wearer never sees. So the write stores
    what will actually be shown and the ack says it was cut.
    """

    if not valid_name(name):
        raise StateError("name rejected: must match the set_name payload check")
    state = read(path, io.get("open_fn"))
    badge = _active_badge(state)
    stored = name[:NAME_MAX]
    badge[KEY_NAME] = stored
    save(state, path, **io)
    return {"stored": stored, "truncated": stored != name}


def set_skin(background, path=None, **io):
    """Write one background id onto the active badge.  NEXT-OPEN semantics.

    ``face`` is deliberately NOT written (see ``KEY_FACE``); setup rederives
    it at open, so a stale face in the file is corrected for free and this module
    needs no copy of the 108-row table.
    """

    resolved = resolve_skin(background)
    if resolved is None:
        raise StateError("skin rejected: not a storable catalogue id")
    state = read(path, io.get("open_fn"))
    badge = _active_badge(state)
    badge[KEY_BACKGROUND] = resolved
    save(state, path, **io)
    return {"stored": resolved}


def live_refresh(enabled=None, path=None, open_fn=None, **io):
    """Signal a RUNNING setup that its state changed.  FLAGGED OFF.

    Present so the seam is real and tested rather than imagined, and returning
    ``False`` without touching the filesystem while ``LIVE_REFRESH_ENABLED`` is
    ``False``. The flag's reason and its cost are recorded at the constant.
    """

    if enabled is None:
        enabled = LIVE_REFRESH_ENABLED
    if not enabled:
        return False
    save({"refresh": True}, path or LIVE_REFRESH_PATH, open_fn=open_fn, **io)
    return True
