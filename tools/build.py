#!/usr/bin/env python3
"""Compile the source export to bytecode and stage the `/system` tree.

THIS FILE SHIPS AS `tools/build.py` INSIDE THE EXPORT, and it is the only script
in there. `scripts/export-source.py` copies it in; it is committed here so it is
tracked, reviewable and gated like everything else.

WHY IT IS NOT `scripts/build_mpy.py`. That script is the canonical builder and it
compiles 28 source trees, including the labs, the archived predecessors and the
networking runtime that this export deliberately omits, from paths shaped like
`badgecard/badge/badgecard`. The export is shaped like `/system`. Pointing the
canonical builder at this tree would fail on the first missing tree, and a
package that fails on its first build is worse than no package. So this is a
same-contract builder for the export's own layout: **the three refusals below are
the ones `scripts/build_mpy.py` exists for, and they are reproduced, not
paraphrased.**

  1. VERSION SKEW. A `.mpy` whose format version disagrees with the firmware
     raises `ValueError: incompatible .mpy file` at import, and an import that
     raises inside `badgeware.launch()` is a modal and a reset -- on every badge,
     not one. So the format version is read out of `mpy-cross` itself and
     compared against the pin, and a mismatch stops the build here.
  2. `.py` WINNING OVER `.mpy`. MicroPython stats the `.py` FIRST and only falls
     back to the bytecode (`py/builtinimport.c`, and its own comment says so). A
     badge holding both runs the source: no speed-up, possibly stale code, and no
     error anywhere. So the output tree is asserted to contain no `.py` outside
     the two roots that are allowed one.
  3. UNVERIFIABLE INSTALLS. An install proves itself by source/device SHA-256
     equality, which bytecode breaks unless the build is reproducible. `--check`
     compiles twice and asserts byte-identical output before any manifest is
     trusted.

WHAT IT NEEDS THAT IS NOT IN THE EXPORT. Two things, both Pimoroni's own and both
carrying no published licence grant for the pinned release, so they are in neither
this export nor the repository it came from:

  * THE FOUR FILES OF THE STOCK LAUNCHER BASE.  `--stock-menu <dir>` verifies
    their pinned hashes and applies the five patches in `apps/menu/PATCHES.json`.
    `--skip-menu` builds everything else and says loudly what is missing.
  * THE TWO STOCK `.af` FACES.  `--stock-fonts <dir>` verifies them against
    `STOCK_FONTS` below and copies them in.  There is NO fetch and no resolver:
    a build that reaches the network is not one anybody should trust, and the
    recipient of this package already has the release on disk.  `--no-stock-fonts`
    is the explicit, printed decision to ship a `/system` with one face.

WHAT IT REFUSES THAT IT DID NOT USED TO, all three from an outside review:

  1. AN APP DIRECTORY THE ROSTER DOES NOT NAME.  The build used to compile every
     directory under `apps/`, so an accidentally copied lab directory would have
     become a shipping app.  `apps-roster.json` is now the roster and this is a
     refusal.
  2. AN INSTALL NOBODY VERIFIED.  `--verify-mount <MOUNT>` compares a mounted
     badge against the build manifest by size and SHA-256, names stray files and
     AppleDouble sidecars, and exits non-zero.  Doing that by hand at 800 units
     is the avoidable human-error surface the review named.
  3. NOTHING, on Windows.  `--check` used to shell out to the Unix `diff`
     executable, which a stock Windows Python does not have -- so the one command
     that PROVES the build would have failed while satisfying the documented
     "Python 3.8+, stdlib only" prerequisite.  It is a hash walk now.

WHEN IT REFUSES, WHICH IS THE FOURTH THING A REVIEW FOUND.  Every refusal above
used to fire AFTER the previous output tree was deleted and the app set compiled,
so a missing `--stock-fonts` argument cost the operator a `/system` that worked.
`preflight()` now runs the whole gate list -- compiler, roster, every app
directory, the four launcher hashes, every patch anchor, both font hashes --
BEFORE anything is written, and the build stages into a temporary sibling of the
output and replaces it only on success.  A refusal at any point leaves the last
good tree exactly where it was.

AND ONE THING IT VERIFIES THAT IS NOT A BUILD AT ALL.  `--verify-manifest` hashes
THIS PACKAGE against its own `MANIFEST.json` and recomputes the `tree_hash`.  It
exists because the package used to tell a reviewer to verify it with three
commands that call the EXPORTER, which is in the canonical repository and not
here: a deploy rehearsal pasted them and got `[Errno 2]`.  The reviewer's
question is "are these the bytes you published", and this answers it with the
tools in front of them -- no compiler, no clones, no network.

USAGE
    python3 tools/build.py --list                # what would be compiled
    python3 tools/build.py --verify-manifest     # are these the published bytes
    python3 tools/build.py --mpy-cross <path> \\
        --stock-menu  <badgeware>/firmware/apps/menu \\
        --stock-fonts <badgeware>/firmware/assets/fonts
    python3 tools/build.py --skip-menu --no-stock-fonts   # partial, loudly
    python3 tools/build.py --check ...           # build twice, prove reproducible
    python3 tools/build.py --verify-mount /Volumes/Tufty2350
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "build", "system")

# THE PIN. Both halves matter and they are checked differently: the mpy MAJOR
# format version is compared against what the compiler emits (a mismatch is a
# reset on every badge), and the firmware tag is recorded in the manifest as a
# claim about what this bytecode was built for.
MPY_FORMAT_MAJOR = 6
TARGET_FIRMWARE = "v3.0.2"

# mpy-cross allocates a FIXED GC arena and its 2 MB default is too small for this
# product: two catalogue tables over 550 KB have already failed with
# `MemoryError: memory allocation failed`, and they grow. 64 MB is host memory in
# a build step, which is free. Worth knowing for its own sake -- a source file
# needing more than 2 MB of compiler arena is a file the BADGE also has to
# compile, in one uninterruptible call, out of its own heap.
MPY_HEAP_BYTES = 64 * 1024 * 1024

# THERE IS NO DEFAULT COMPILER PATH, and that absence is deliberate.  This
# resolved `~/.cache/badge-playground/.../mpy-cross` until 2026-08-24, which meant
# exactly one machine -- the maintainer's -- built with a compiler nobody had
# named on the command line, silently, out of a cache that could be any age, while
# every other reader got the documented error.  A deploy rehearsal found it by
# running `tools/build.py` with no `--mpy-cross` and getting a build instead of
# the `make` line `BUILDING.md` §1.2 promises.  Two sources, both explicit.
MPY_CROSS_SOURCES = ("--mpy-cross", "MPY_CROSS")

# `/system/main.py` ships as SOURCE, not bytecode: the frozen boot imports it by
# path and it is under a kilobyte, so there is nothing to win and a format to get
# wrong. `secrets.py` is the other one, for the same reason plus a bigger one --
# it is the file a per-unit provisioning step REWRITES, and bytecode is not a
# thing an operator can edit.
SOURCE_ROOTS = ("main.py", "secrets.py")

# THE SECRETS TEMPLATE, and it is emitted rather than shipped in this package.
# Badgeware's frozen `secrets` helper reads `/secrets.py` first and falls back to
# `/system/secrets.py`, so this file is what an UNPROVISIONED badge reads:
# present, with every value EMPTY, so a missing provision is an empty string
# rather than an ImportError.
#
# WHY THE BUILDER WRITES IT AND THE EXPORT DOES NOT CONTAIN IT.  An adversarial
# review found the source builder emitting no template at all while the release
# pipeline's exporter emits an eight-key one -- so a `/system` staged from this
# package was missing a file a badge flashed from the release artifact has, and
# `--verify-mount` against such a badge would have reported it as a stray. The
# template belongs in the BUILD OUTPUT, not in a source export whose whole
# secrets gate is "there is no `secrets.py` in this tree".
#
# NEVER POPULATED HERE, BY ANYTHING, EVER. The per-unit file is provisioned
# separately and must be a SUPERSET of these keys.
SECRETS_KEYS = (
    ("WIFI_SSID", "venue network name; per-badge or per-batch"),
    ("WIFI_PASSWORD", "venue network password"),
    ("REGION", "two-letter Wi-Fi regulatory domain, e.g. CA"),
    ("TIMEZONE", "IANA zone, e.g. America/Edmonton"),
    ("BADGELINK_JWT", "per-badge ES256 JWT; identity claims only"),
    ("BADGELINK_APIKEY", "the project's publishable (anon) key"),
    ("BADGELINK_HOST", "the realtime host; drives SNI and TLS verification"),
    ("BADGELINK_IP", "optional pre-resolved IPv4; empty means resolve off-frame"),
)

# Not compiled, not installed. Export furniture and the one worked-example suite.
SKIP_NAMES = ("README.md", "MANIFEST.json", "PATCHES.json")
SKIP_DIRS = ("tests", "shared", "tools", "__pycache__")

MENU_DIR = "menu"
PATCHES_NAME = "PATCHES.json"
ROSTER_NAME = "apps-roster.json"

# THE TWO STOCK FACES, and these are the same constants the project's bytecode
# exporter refuses on, so the two artifacts cannot disagree about which bytes a
# badge carries. They live in a v3.0.2 release clone at
# `<badgeware>/firmware/assets/fonts/`.
STOCK_FONTS = {
    "DynaPuff-Medium.af":
        "e15bd8b9709b6196da4b4fa74a94ca3f23a24d9b9fd8d8776d733136cd74649b",
    "IndieFlower-Regular.af":
        "a917728b392046f7bcd90575652613884af7bd3e9c435b7ca8b93cb07fae935c",
}

# `._*` is macOS's AppleDouble sidecar and `.DS_Store` is its folder state. On a
# FAT volume a sidecar under `apps/` is a file the badge tries to IMPORT, so the
# mount verifier names them rather than ignoring them.
SIDECAR_PREFIXES = ("._",)
SIDECAR_NAMES = (".DS_Store", "Thumbs.db")


class BuildError(Exception):
    """A refusal. Every one of these is a named production stop."""


def digest_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def digest(path):
    with open(path, "rb") as handle:
        return digest_bytes(handle.read())


# ---------------------------------------------------------------------------
# The compiler
# ---------------------------------------------------------------------------

def resolve_mpy_cross(explicit=None):
    """The compiler, from the flag or the environment. Nothing else. See above."""
    for candidate in (explicit, os.environ.get("MPY_CROSS")):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise BuildError(
        "mpy-cross not found, and this build has no default path to fall back\n"
        "on: %s are the only two sources, so every machine\n"
        "resolves the same compiler or none.\n"
        "Build it from the MicroPython clone that matches the firmware you are\n"
        "flashing (BUILDING.md section 1.2 pins the commit):\n"
        "    make -C <micropython>/mpy-cross\n"
        "then pass --mpy-cross <path> or set MPY_CROSS."
        % " and ".join(MPY_CROSS_SOURCES))


def check_compiler(mpy_cross):
    """The version gate. Reads the compiler rather than trusting the pin."""
    result = subprocess.run([mpy_cross, "--version"], capture_output=True, text=True)
    banner = ((result.stdout or "") + (result.stderr or "")).strip()
    match = re.search(r"emitting mpy v(\d+)\.(\d+)", banner)
    if not match:
        raise BuildError("could not parse an mpy version from: %s" % banner)
    major, minor = int(match.group(1)), int(match.group(2))
    if major != MPY_FORMAT_MAJOR:
        raise BuildError(
            "REFUSING TO BUILD: mpy format version mismatch.\n"
            "  this export targets Badgeware %s, which loads mpy v%d.x\n"
            "  your mpy-cross emits v%d.%d (%s)\n"
            "Shipping this would raise 'incompatible .mpy file' at import on\n"
            "every badge, and an import that raises inside launch() resets the\n"
            "badge. Rebuild mpy-cross from the matching MicroPython clone."
            % (TARGET_FIRMWARE, MPY_FORMAT_MAJOR, major, minor, banner))
    # The SUB version is deliberately NOT compared: the loader only checks it
    # when the arch byte is non-zero (native or viper code), and this product
    # emits pure bytecode. Comparing it would reject builds that would work.
    #
    # THE BANNER'S BUILD DATE IS STRIPPED BEFORE IT IS RECORDED, and that is a
    # determinism fix. `mpy-cross --version` prints `... on 2026-08-21; ...`, and
    # this dict goes into `manifest.json` -- so rebuilding the SAME compiler
    # source on a different day changed the manifest while every compiled byte
    # stayed identical. An adversarial review called that a wall-clock value in
    # built output and it is one. The commit-ish and the mpy format, which are
    # what actually identify the compiler, are kept; the raw banner is kept too,
    # outside the manifest, so a human can still read what ran.
    return {"mpy_format": "v%d.%d" % (major, minor),
            "banner": _normalize_banner(banner),
            "banner_date_stripped": bool(BANNER_DATE.search(banner))}


# `MicroPython v1.14-6910.gb29530abbd.dirty on 2026-08-21; mpy-cross emitting...`
BANNER_DATE = re.compile(r"\s+on\s+\d{4}-\d{2}-\d{2}")


def _normalize_banner(banner):
    return BANNER_DATE.sub("", banner).strip()


def compile_module(mpy_cross, source, dest, embed_name):
    """One module, with `-s` naming the path it will have ON THE BADGE.

    THE `-s` IS LOAD-BEARING AND IT WAS FOUND THE HARD WAY. mpy-cross embeds the
    input filename as the traceback filename, so without `-s` the emitted bytes
    carry wherever the file happened to be read from. Two consequences, both
    real: the build machine's directory layout leaks into every on-device
    traceback, and the build stops being reproducible. `--check` caught exactly
    that on the two patched launcher modules, which are staged to a scratch
    directory before compiling -- the scratch path differed between the two runs,
    so two identical inputs produced two different `.mpy` files.

    So the name is DECLARED as the badge-relative path (`apps/menu/app.py`)
    rather than derived from where the bytes were read. A traceback on the badge
    then names a file that exists in this export, which is the whole point.
    """
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    result = subprocess.run(
        [mpy_cross, "-X", "heapsize=%d" % MPY_HEAP_BYTES,
         "-s", embed_name, "-o", dest, source],
        capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        raise BuildError("mpy-cross failed on %s\n%s%s"
                         % (embed_name, result.stdout, result.stderr))


# ---------------------------------------------------------------------------
# The launcher's stock base
# ---------------------------------------------------------------------------

def load_patches():
    path = os.path.join(ROOT, "apps", MENU_DIR, PATCHES_NAME)
    if not os.path.isfile(path):
        raise BuildError("%s is missing; the launcher cannot be built"
                         % os.path.relpath(path, ROOT))
    with open(path, "r") as handle:
        document = json.load(handle)
    for key in ("pinned_sha256", "patches", "stock_files"):
        if key not in document:
            raise BuildError("%s has no '%s'" % (PATCHES_NAME, key))
    return document


def read_menu_base(stock_menu, patches):
    """Verify the four stock files and patch them IN MEMORY. Writes nothing.

    Verified BEFORE substituting, which is the whole reason the hashes are
    pinned: every replacement below is applied to bytes proven to be the pinned
    base's, so a drifted base is a refusal rather than a patch that silently
    matched half of something.

    IT WRITES NOTHING ON PURPOSE, and that is the preflight fix.  Both refusals
    in here -- a drifted base and a stale patch anchor -- used to fire AFTER
    `build()` had already deleted the previous output tree and compiled every
    app, so the operator paid the whole build to be told the launcher input was
    wrong and lost a known-good `/system` doing it.  `build()` calls this before
    it removes anything, then stages the payloads it returns.
    """
    stock_menu = os.path.abspath(os.path.expanduser(stock_menu))
    if not os.path.isdir(stock_menu):
        raise BuildError("--stock-menu is not a directory: %s" % stock_menu)
    wanted = patches["pinned_sha256"]
    for name in sorted(wanted):
        path = os.path.join(stock_menu, name)
        if not os.path.isfile(path):
            raise BuildError(
                "the stock launcher base is incomplete: %s is missing from %s\n"
                "Expected the four files %s."
                % (name, stock_menu, ", ".join(sorted(wanted))))
        actual = digest(path)
        if actual != wanted[name]:
            raise BuildError(
                "REFUSING: stock launcher base has drifted.\n"
                "  %s\n    expected %s\n    got      %s\n"
                "This export's patches were written against the pinned bytes. A\n"
                "launcher patched into a base it was not written for looks normal\n"
                "and silently loses a feature."
                % (name, wanted[name], actual))

    # Our own `ui.py` REPLACES the stock file of that name; it is already in the
    # export's `apps/menu/`, so it is compiled with everything else and is not
    # taken from the base at all.
    replaced = set(patches.get("replaced_stock_files", ()))
    base = []
    for name in sorted(wanted):
        if name in replaced:
            continue
        with open(os.path.join(stock_menu, name), "rb") as handle:
            payload = handle.read()
        applied = []
        for patch in patches["patches"]:
            if patch["file"] != name:
                continue
            anchor = patch["anchor"].encode()
            if anchor not in payload:
                raise BuildError(
                    "REFUSING: the %s patch's anchor is not in %s.\n"
                    "  why: %s\n"
                    "The hash gate passed, so this is a patch register that has\n"
                    "gone stale rather than a wrong base."
                    % (patch["name"], name, patch["why"]))
            payload = payload.replace(anchor, patch["replacement"].encode(), 1)
            applied.append(patch["name"])
        base.append({"file": name, "patches": applied, "bytes": len(payload),
                     "payload": payload})
    return base


def write_menu_base(base, dest):
    """The already-verified payloads, onto disk for the compiler to read."""
    os.makedirs(dest, exist_ok=True)
    for entry in base:
        with open(os.path.join(dest, entry["file"]), "wb") as handle:
            handle.write(entry["payload"])
    return [{key: value for key, value in entry.items() if key != "payload"}
            for entry in base]


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------

def payload_files(app_root):
    """`(rel, abs)` for everything in one app that installs, sorted."""
    out = []
    for base, dirs, files in os.walk(app_root):
        dirs[:] = sorted(d for d in dirs
                         if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            if name in SKIP_NAMES or name.startswith("."):
                continue
            abs_path = os.path.join(base, name)
            out.append((os.path.relpath(abs_path, app_root).replace(os.sep, "/"),
                        abs_path))
    return out


def load_roster():
    """`apps-roster.json`: the lineup, and the only thing this build compiles.

    THE ROSTER IS A GATE, NOT A HINT.  This build used to enumerate `apps/` and
    compile whatever it found, which means a directory copied in by accident -- a
    lab tile, a comparison harness, a half-finished experiment -- would have
    become a shipping app with an icon on a wearer's grid, silently, at 800 units.
    The roster is the file the project's two exporters already coordinate through,
    so reading it here makes the three artifacts agree by construction.
    """
    path = os.path.join(ROOT, ROSTER_NAME)
    if not os.path.isfile(path):
        raise BuildError(
            "%s is missing. It is the lineup this build compiles: without it "
            "there is no way to tell a shipping app from a directory somebody "
            "copied in. Re-export, or run with --allow-unrostered and read the "
            "list it prints." % ROSTER_NAME)
    with open(path, "r") as handle:
        document = json.load(handle)
    for key in ("apps", "launcher"):
        if key not in document:
            raise BuildError("%s has no '%s'" % (ROSTER_NAME, key))
    return document


def app_dirs(roster=None, allow_unrostered=False):
    """The directories to compile: the roster's, in the roster's grid order.

    Order is load-bearing rather than cosmetic -- it is the launcher's grid order
    and `order.txt` carries it -- so the roster's sequence is preserved instead of
    being sorted.
    """
    apps_root = os.path.join(ROOT, "apps")
    if not os.path.isdir(apps_root):
        raise BuildError("no apps/ directory beside %s; run this from inside the export"
                         % os.path.relpath(os.path.abspath(__file__), ROOT))
    present = sorted(name for name in os.listdir(apps_root)
                     if os.path.isdir(os.path.join(apps_root, name)))
    if roster is None:
        return present
    named = list(roster["apps"]) + [roster["launcher"]]
    missing = [name for name in named if name not in present]
    if missing:
        raise BuildError(
            "REFUSING: %s names %d app(s) that are not in this tree:\n  %s\n"
            "The roster and the export disagree, so neither can be trusted about "
            "what ships." % (ROSTER_NAME, len(missing), "\n  ".join(missing)))
    stray = [name for name in present if name not in named]
    if stray and not allow_unrostered:
        raise BuildError(
            "REFUSING: %d directory(ies) under apps/ that %s does not name:\n  %s\n"
            "An unrostered directory compiles into a shipping app with a tile on "
            "the wearer's grid. Add it to the roster deliberately, delete it, or "
            "pass --allow-unrostered if you know it is a local experiment."
            % (len(stray), ROSTER_NAME, "\n  ".join(stray)))
    return named + stray


def verify_stock_fonts(stock_fonts):
    """The two stock faces, existence- and hash-checked. Copies nothing.

    This is the step `assets/fonts/README.md` used to CLAIM the build did and did
    not. An outside reviewer walked the build against that page, found no
    resolution step, and correctly called it the first hard build blocker in the
    package: the export documented a finished `/system` with three faces and had
    no path to two of them. There is a path now and it is an input rather than a
    download, verified before it is trusted.

    SPLIT FROM THE COPY on 2026-08-24 so `build()` can run it as a PREFLIGHT. A
    second reviewer noted that the refusal, while true, was LATE: the build
    deleted the previous `/system` and compiled every app before finding out that
    a required input was absent or had drifted.
    """
    stock_fonts = os.path.abspath(os.path.expanduser(stock_fonts))
    if not os.path.isdir(stock_fonts):
        raise BuildError("--stock-fonts is not a directory: %s" % stock_fonts)
    verified = []
    for name in sorted(STOCK_FONTS):
        path = os.path.join(stock_fonts, name)
        if not os.path.isfile(path):
            raise BuildError(
                "the stock font %s is not in %s\n"
                "In a Badgeware %s release clone the two faces are at\n"
                "  <badgeware>/firmware/assets/fonts/\n"
                "Expected both of: %s."
                % (name, stock_fonts, TARGET_FIRMWARE, ", ".join(sorted(STOCK_FONTS))))
        actual = digest(path)
        if actual != STOCK_FONTS[name]:
            raise BuildError(
                "REFUSING: stock font %s has drifted.\n"
                "  expected %s\n  got      %s\n"
                "This is a byte-exact release asset. A different face is a"
                " different set of advances, and this product measures text."
                % (name, STOCK_FONTS[name], actual))
        verified.append({"file": name, "sha256": actual,
                         "bytes": os.path.getsize(path), "source": path})
    return verified


def write_stock_fonts(verified, dest):
    """The already-verified faces, copied. No hashing here: that already ran."""
    os.makedirs(dest, exist_ok=True)
    for entry in verified:
        shutil.copyfile(entry["source"], os.path.join(dest, entry["file"]))
    return [{key: value for key, value in entry.items() if key != "source"}
            for entry in verified]


def stage_stock_fonts(stock_fonts, dest):
    """Verify the two stock faces and copy them. No fetch, by design."""
    return write_stock_fonts(verify_stock_fonts(stock_fonts), dest)


def preflight(mpy_cross, stock_menu=None, skip_menu=False, stock_fonts=None,
              no_stock_fonts=False, allow_unrostered=False):
    """EVERY REFUSAL THIS BUILD OWNS, RUN BEFORE IT TOUCHES ANYTHING.

    THE DEFECT THIS FIXES, in the words of the outside review that found it:
    "`build()` removes the previous output at lines 454-456, compiles the app
    set, and only later refuses missing menu or font inputs. Validate every
    required path and every pinned stock hash before deleting a known-good
    output or doing expensive compilation."  Both halves of that were true and
    the second is the expensive one -- the compiler pass is ~150 modules -- but
    the first is the one that costs something you cannot get back: a `/system`
    tree that installed and booted, deleted to make room for a build that then
    refused on an argument the operator could have been told about immediately.

    So this function is the whole gate list, in cost order, with nothing written:

      * the compiler resolves and emits the pinned mpy MAJOR format version;
      * `apps-roster.json` parses and names `apps` and `launcher`;
      * every rostered app directory exists, and no unrostered one does;
      * every rostered app has at least one file to install;
      * the four stock launcher files exist, hash to their pins, and every
        patch anchor in `PATCHES.json` is present in the bytes it patches;
      * both stock `.af` faces exist and hash to their pins, or the build was
        told out loud to ship one face.

    It returns the validated inputs, so nothing is read or hashed twice: the
    patched launcher bytes and the verified font paths come back with it.
    """
    compiler = check_compiler(mpy_cross)
    roster = load_roster()
    apps = app_dirs(roster, allow_unrostered=allow_unrostered)

    empty = []
    for app in apps:
        if app == MENU_DIR and skip_menu:
            continue
        if not payload_files(os.path.join(ROOT, "apps", app)):
            empty.append(app)
    if empty:
        raise BuildError(
            "REFUSING: %d rostered app(s) with nothing to install:\n  %s\n"
            "An empty app directory compiles to an empty tile: the launcher\n"
            "draws it and opening it resets the badge."
            % (len(empty), "\n  ".join(empty)))

    menu_base = []
    if not skip_menu:
        if not stock_menu:
            raise BuildError(
                "the launcher needs the four stock base files, which are\n"
                "Pimoroni's own and are not in this export (no published licence\n"
                "grant for the pinned release).\n"
                "  pass --stock-menu <badgeware clone>/firmware/apps/menu\n"
                "  or   --skip-menu to build everything else\n"
                "See apps/menu/README.md.")
        menu_base = read_menu_base(stock_menu, load_patches())

    fonts_verified = []
    if stock_fonts:
        fonts_verified = verify_stock_fonts(stock_fonts)
    elif not no_stock_fonts:
        raise BuildError(
            "the two stock `.af` faces are missing and they SHIP on a finished\n"
            "badge (%s).\n"
            "They are Pimoroni's own, byte-exact release assets with no published\n"
            "licence grant for the pinned release, so they are not in this export.\n"
            "  pass --stock-fonts <badgeware>/firmware/assets/fonts\n"
            "  or   --no-stock-fonts to accept a /system with one face\n"
            "See assets/fonts/README.md." % ", ".join(sorted(STOCK_FONTS)))

    return {"compiler": compiler, "roster": roster, "apps": apps,
            "menu_base": menu_base, "fonts": fonts_verified}


def build(out, mpy_cross, stock_menu=None, skip_menu=False, stock_fonts=None,
          no_stock_fonts=False, allow_unrostered=False, quiet=False):
    """Compile and stage `/system`. The output is replaced only on success.

    STAGED, THEN SWAPPED.  Everything below writes into a sibling directory of
    `out` and the previous output is removed at the very end, one `os.replace`
    from the finished tree.  A refusal anywhere -- a stray `.py`, a tree over the
    12 MB `/system` budget, a compiler failure on file 140 of 150 -- therefore
    leaves the last good build exactly where it was.  It used to delete first
    and refuse later, which is how an operator ended up with no `/system` at all
    over an argument they could have fixed in a second.
    """
    checked = preflight(mpy_cross, stock_menu=stock_menu, skip_menu=skip_menu,
                        stock_fonts=stock_fonts, no_stock_fonts=no_stock_fonts,
                        allow_unrostered=allow_unrostered)
    compiler = checked["compiler"]
    roster = checked["roster"]

    parent = os.path.dirname(os.path.abspath(out)) or "."
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".build-staging-", dir=parent)
    try:
        manifest = _stage(staging, mpy_cross, checked, skip_menu=skip_menu,
                          out_label=out, quiet=quiet)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.replace(staging, out)
    return manifest


def _stage(out, mpy_cross, checked, skip_menu=False, out_label=None, quiet=False):
    """The build itself, into a directory nobody is depending on yet.

    `out_label` is what the report prints, because `out` here is the staging
    directory and the operator cares about where the tree lands.
    """
    compiler = checked["compiler"]
    roster = checked["roster"]

    compiled = 0
    copied = 0
    source_bytes = 0
    rows = []
    menu_staged = []
    fonts_staged = []

    for app in checked["apps"]:
        app_root = os.path.join(ROOT, "apps", app)
        if app == MENU_DIR and skip_menu:
            continue
        dest_root = os.path.join(out, "apps", app)
        for rel, abs_path in payload_files(app_root):
            if rel.endswith(".py"):
                dest = os.path.join(dest_root, rel[:-3] + ".mpy")
                compile_module(mpy_cross, abs_path, dest,
                               "apps/%s/%s" % (app, rel))
                source_bytes += os.path.getsize(abs_path)
                compiled += 1
            else:
                dest = os.path.join(dest_root, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copyfile(abs_path, dest)
                copied += 1
        rows.append(app)

    if not skip_menu:
        # The four files were verified and patched IN MEMORY by `preflight`.
        # They land on disk here only because `mpy-cross` takes a path.
        staged_dir = os.path.join(out, ".stock-menu")
        menu_staged = write_menu_base(checked["menu_base"], staged_dir)
        for entry in menu_staged:
            abs_path = os.path.join(staged_dir, entry["file"])
            if entry["file"].endswith(".py"):
                compile_module(
                    mpy_cross, abs_path,
                    os.path.join(out, "apps", MENU_DIR,
                                 entry["file"][:-3] + ".mpy"),
                    "apps/%s/%s" % (MENU_DIR, entry["file"]))
                compiled += 1
            else:
                shutil.copyfile(abs_path,
                                os.path.join(out, "apps", MENU_DIR, entry["file"]))
                copied += 1
        shutil.rmtree(staged_dir)

    for name in SOURCE_ROOTS:
        source = os.path.join(ROOT, name)
        if os.path.isfile(source):
            shutil.copyfile(source, os.path.join(out, name))
            copied += 1

    # THE EMPTY TEMPLATE, written rather than copied. Deterministic: a sorted
    # constant table and no clock.
    secrets_path = os.path.join(out, "secrets.py")
    if not os.path.isfile(secrets_path):
        lines = [
            '"""Per-unit provisioning slots. EVERY VALUE HERE IS EMPTY.',
            "",
            "Badgeware's frozen `secrets` helper reads `/secrets.py` first and",
            "falls back to this file, so an unprovisioned badge gets empty",
            "strings rather than an ImportError. Provision the per-unit",
            "`/secrets.py` separately; it must be a SUPERSET of these keys.",
            "",
            "NOTHING IN THIS BUILD READS THEM. The network runtime is not part of",
            'the source export (`apps-roster.json` -> `system_lib.ship`), so this',
            "file is here for parity with the release artifact and for the day the",
            "radio is turned on.",
            '"""',
            "",
        ]
        for key, why in SECRETS_KEYS:
            lines.append("%s = \"\"  # %s" % (key, why))
        with open(secrets_path, "w") as handle:
            handle.write("\n".join(lines) + "\n")
        copied += 1

    fonts = os.path.join(ROOT, "assets", "fonts")
    font_dest = os.path.join(out, "assets", "fonts")
    if os.path.isdir(fonts):
        os.makedirs(font_dest, exist_ok=True)
        for name in sorted(os.listdir(fonts)):
            if name in SKIP_NAMES or name.startswith("."):
                continue
            shutil.copyfile(os.path.join(fonts, name), os.path.join(font_dest, name))
            copied += 1

    # THE OTHER TWO FACES. Required unless refused out loud: this tree replaces
    # `/system` wholesale, so a missing stock face is a REMOVAL from a stock badge
    # rather than an omission from a package. Existence and both pinned hashes
    # were checked by `preflight`; this is the copy.
    if checked["fonts"]:
        fonts_staged = write_stock_fonts(checked["fonts"], font_dest)
        copied += len(fonts_staged)

    # REFUSAL 2, asserted rather than trusted.
    strays = []
    for base, _dirs, files in os.walk(out):
        for name in files:
            if not name.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(base, name), out).replace(os.sep, "/")
            if rel not in SOURCE_ROOTS:
                strays.append(rel)
    if strays:
        raise BuildError(
            "REFUSING: %d .py file(s) in the output tree. MicroPython stats .py\n"
            "first, so these would shadow their own bytecode:\n  %s"
            % (len(strays), "\n  ".join(sorted(strays))))

    manifest = {
        "schema": "badge-source-export-build/1",
        "target_firmware": TARGET_FIRMWARE,
        "compiler": compiler,
        "roster": {"apps": list(roster["apps"]), "launcher": roster["launcher"]},
        "apps": rows,
        "menu": menu_staged or "skipped",
        "stock_fonts": fonts_staged or "not supplied",
        "counts": {"compiled": compiled, "copied": copied},
        "files": [],
    }
    total = 0
    for base, dirs, files in os.walk(out):
        dirs[:] = sorted(dirs)
        for name in sorted(files):
            path = os.path.join(base, name)
            rel = os.path.relpath(path, out).replace(os.sep, "/")
            if rel == "manifest.json":
                continue
            size = os.path.getsize(path)
            total += size
            manifest["files"].append(
                {"path": rel, "bytes": size, "sha256": digest(path)})
    manifest["files"].sort(key=lambda row: row["path"])
    manifest["totals"] = {"files": len(manifest["files"]), "bytes": total,
                          "source_bytes": source_bytes}
    manifest["tree_hash"] = digest_bytes("".join(
        "%s\0%s\n" % (row["path"], row["sha256"])
        for row in manifest["files"]).encode())
    with open(os.path.join(out, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")

    # The 12 MB FAT allocation the badge's filesystem is packed into. Over it is
    # not a slow install, it is an install that cannot happen.
    budget = 3072 * 4096
    if total > budget:
        raise BuildError(
            "REFUSING: the staged tree is %s bytes against a %s byte /system\n"
            "budget. Prune an asset profile (see the roster in the full\n"
            "repository) rather than dropping a module."
            % ("{:,}".format(total), "{:,}".format(budget)))

    if not quiet:
        print("BUILD %s" % os.path.relpath(out_label or out, ROOT))
        print("  compiler   %s" % compiler["banner"])
        print("  apps       %s" % ", ".join(rows))
        if skip_menu:
            print("  menu       SKIPPED -- the launcher is not in this tree")
        else:
            print("  menu       %s"
                  % "; ".join("%s [%s]" % (row["file"], ", ".join(row["patches"]) or "verbatim")
                              for row in menu_staged))
        # THE ROSTER LINE STATES WHAT WAS STAGED, not what the roster names. It
        # printed "N apps + menu" one line below "menu SKIPPED" until 2026-08-24,
        # which a deploy rehearsal flagged as the build contradicting itself in
        # two consecutive lines.
        print("  roster     %d apps%s (apps-roster.json)"
              % (len(roster["apps"]),
                 "" if skip_menu else " + %s" % roster["launcher"]))
        if fonts_staged:
            print("  fonts      %s (hashes verified)"
                  % ", ".join(row["file"] for row in fonts_staged))
        else:
            print("  fonts      ⚠ ONE FACE ONLY -- %s are not in this /system"
                  % ", ".join(sorted(STOCK_FONTS)))
        print("  compiled   %d modules from %s bytes of source"
              % (compiled, "{:,}".format(source_bytes)))
        print("  copied     %d assets" % copied)
        print("  total      %s bytes of %s (%d%% of the /system budget)"
              % ("{:,}".format(total), "{:,}".format(budget), total * 100 // budget))
        print("  tree hash  %s" % manifest["tree_hash"])
        # A DEGRADED TREE SAYS SO, LOUDLY AND LAST. `--skip-menu` and
        # `--no-stock-fonts` each replace a complete `build/system` with one that
        # would regress a stock badge, and the replacement is silent: a deploy
        # rehearsal ran them over a good build and got no warning that the good
        # build was gone, then verified a mount against the degraded manifest.
        # Last, because the line above it is the one an operator reads.
        missing = []
        if skip_menu:
            missing.append("the launcher (apps/%s)" % MENU_DIR)
        if not fonts_staged:
            missing.append("the two stock faces (%s)"
                           % ", ".join(sorted(STOCK_FONTS)))
        if missing:
            print("  ⚠ DEGRADED BUILD -- this /system is missing %s."
                  % " and ".join(missing))
            print("    It has REPLACED any previous build/system, and this tree")
            print("    replaces a badge's /system wholesale, so installing it")
            print("    REMOVES those from the badge. --verify-mount compares")
            print("    against THIS manifest and will call the result verified.")
            print("    Rebuild with --stock-menu/--stock-fonts before installing.")
    return manifest


def tree_index(root):
    """`{relative path: (bytes, sha256)}` for a whole tree, sorted walk."""
    index = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(dirs)
        for name in sorted(files):
            path = os.path.join(base, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            index[rel] = (os.path.getsize(path), digest(path))
    return index


def compare_trees(first, second, labels=("run 1", "run 2")):
    """Every difference between two trees. Empty list means byte-identical.

    PURE PYTHON, and that is a portability FIX rather than a preference. This
    check used to shell out to the Unix `diff` executable, so on a stock Windows
    Python -- which satisfies the documented "3.8 or newer, stdlib only"
    prerequisite exactly -- the one command that proves the artifact is
    reproducible would have failed with `FileNotFoundError`. Hashing both trees
    in-process is also a STRONGER check than `diff -q`: it reports the pair of
    hashes rather than "files differ".
    """
    left, right = tree_index(first), tree_index(second)
    lines = []
    for rel in sorted(set(left) - set(right)):
        lines.append("only in %s: %s" % (labels[0], rel))
    for rel in sorted(set(right) - set(left)):
        lines.append("only in %s: %s" % (labels[1], rel))
    for rel in sorted(set(left) & set(right)):
        if left[rel] != right[rel]:
            lines.append("differs: %s (%d B %s vs %d B %s)"
                         % (rel, left[rel][0], left[rel][1][:12],
                            right[rel][0], right[rel][1][:12]))
    return lines


def check(mpy_cross, stock_menu, skip_menu, stock_fonts=None,
          no_stock_fonts=False, allow_unrostered=False):
    hashes = []
    with tempfile.TemporaryDirectory() as scratch:
        for index in (1, 2):
            manifest = build(os.path.join(scratch, "run%d" % index), mpy_cross,
                             stock_menu=stock_menu, skip_menu=skip_menu,
                             stock_fonts=stock_fonts,
                             no_stock_fonts=no_stock_fonts,
                             allow_unrostered=allow_unrostered, quiet=True)
            hashes.append(manifest["tree_hash"])
        first, second = (os.path.join(scratch, "run1"),
                         os.path.join(scratch, "run2"))
        differences = compare_trees(first, second)
        counted = len(tree_index(first))
    print("REPRODUCIBILITY CHECK")
    print("  run 1  %s" % hashes[0])
    print("  run 2  %s" % hashes[1])
    if hashes[0] != hashes[1] or differences:
        for line in differences[:40]:
            print("  %s" % line)
        raise BuildError("the build is NOT reproducible; do not trust its manifest")
    print("  RESULT byte-identical (%d files hashed in both runs)" % counted)
    print("  NOTE   --check builds into a temporary directory and does NOT")
    print("         populate build/system. Run a normal build for the install")
    print("         tree; this command only proves the build is reproducible.")


# ---------------------------------------------------------------------------
# Verifying an install
# ---------------------------------------------------------------------------

def verify_mount(mount, manifest_path=None):
    """Compare a mounted badge against the build manifest. The install's proof.

    WHY THIS IS A COMMAND AND NOT A CHECKLIST.  `BUILDING.md` used to ask the
    operator to identify stale directories, delete them, copy every subtree, look
    for stray `.py` and AppleDouble files, and compare every size and hash by
    hand.  An outside reviewer called that an avoidable human-error surface at
    800 units and was right: every one of those steps is mechanical, and the
    manifest the build already writes has every number in it.

    Four findings, and each one is a real install failure that has happened to
    somebody:

      * MISSING or WRONG BYTES -- the install did not take, or took a stale copy;
      * A STRAY `.py` -- MicroPython stats source FIRST, so a `.py` beside its
        own `.mpy` runs the source: no speed-up, possibly stale code, no error;
      * AN APPLEDOUBLE SIDECAR -- a `._foo.mpy` under `apps/` is a file the badge
        tries to import.  FAT copies on macOS create them even with an rsync
        exclude;
      * AN UNEXPECTED DIRECTORY -- a tile for an app the lineup no longer names,
        pointing at code that is gone.  In one real case 3.82 MB of it.

    Read-only: it never writes to or deletes from the volume.  What to remove is
    the operator's call, and it is printed as a list.
    """
    mount = os.path.abspath(os.path.expanduser(mount))
    if not os.path.isdir(mount):
        raise BuildError("--verify-mount is not a directory: %s" % mount)
    manifest_path = manifest_path or os.path.join(DEFAULT_OUT, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise BuildError(
            "no build manifest at %s\nRun a normal build first: the manifest is "
            "what an install is verified AGAINST."
            % os.path.relpath(manifest_path, ROOT))
    with open(manifest_path, "r") as handle:
        manifest = json.load(handle)

    expected = {row["path"]: (row["bytes"], row["sha256"])
                for row in manifest["files"] if row["path"] != "manifest.json"}
    found = tree_index(mount)

    missing = sorted(set(expected) - set(found))
    wrong = sorted(rel for rel in set(expected) & set(found)
                   if found[rel] != expected[rel])
    extra = sorted(set(found) - set(expected))
    strays = [rel for rel in found
              if rel.endswith(".py") and rel not in SOURCE_ROOTS]
    sidecars = [rel for rel in found
                if os.path.basename(rel).startswith(SIDECAR_PREFIXES)
                or os.path.basename(rel) in SIDECAR_NAMES]
    # A top-level directory the build does not emit is a stale app tile. Reported
    # separately from `extra` because the fix is different: extra FILES are
    # usually sidecars, an extra DIRECTORY is an app that should not be there.
    build_roots = set(rel.split("/")[0] for rel in expected)
    stale_roots = sorted(
        name for name in os.listdir(mount)
        if os.path.isdir(os.path.join(mount, name)) and name not in build_roots)
    stale_apps = []
    if "apps" in build_roots and os.path.isdir(os.path.join(mount, "apps")):
        installed = set(rel.split("/")[1] for rel in expected
                        if rel.startswith("apps/") and "/" in rel[5:])
        stale_apps = sorted(
            name for name in os.listdir(os.path.join(mount, "apps"))
            if os.path.isdir(os.path.join(mount, "apps", name))
            and name not in installed)

    print("MOUNT VERIFY %s" % mount)
    print("  manifest   %s (%d files, tree hash %s)"
          % (os.path.relpath(manifest_path, ROOT), len(expected),
             manifest.get("tree_hash", "?")[:12]))
    print("  on volume  %d files" % len(found))
    rows = [("missing from the volume", missing),
            ("wrong size or hash", wrong),
            ("on the volume and not in the build", extra),
            ("stray .py (shadows its own bytecode)", strays),
            ("AppleDouble/OS sidecars", sidecars),
            ("stale app directories under apps/", stale_apps),
            ("unexpected top-level directories", stale_roots)]
    for label, items in rows:
        marker = "ok " if not items else "FAIL"
        print("  %s %-38s %d" % (marker, label, len(items)))
        for item in items[:20]:
            print("        - %s" % item)
        if len(items) > 20:
            print("        ... and %d more" % (len(items) - 20))
    if any(items for _label, items in rows):
        # THE REMEDIATION NAMES ALL FOUR ROOTS, not just `apps/`. It said "mirror
        # the failing app directories again" until 2026-08-24, which does not
        # describe the failure this verifier catches most often: a deploy
        # rehearsal followed an install procedure that copied `apps/` alone, and
        # the volume kept Pimoroni's `main.py`, its `secrets.py` and 16 stock
        # asset files. The check found it; the advice underneath it pointed at
        # the wrong directory.
        raise BuildError(
            "THE INSTALL IS NOT VERIFIED. Equality with the build manifest is "
            "the install's only proof; anything less is a hope.\n"
            "The install is four roots, not one. Clear and recopy:\n"
            "    rm -r \"<MOUNT>/apps\" \"<MOUNT>/assets\"\n"
            "    cp -R build/system/apps build/system/assets \\\n"
            "          build/system/main.py build/system/secrets.py \"<MOUNT>/\"\n"
            "Copy the roots BY NAME (`build/system/.` also installs "
            "manifest.json, which the build did not emit), delete anything "
            "listed above that the build does not emit, and re-run this "
            "command.")
    print("  RESULT every installed file matches the build, byte for byte, with "
          "no strays")


# What is legitimately in this package and not in `MANIFEST.json`: the build's own
# output tree, and the bytecode CPython writes beside the shipped test suite the
# moment anybody runs it. Both are in the emitted `.gitignore` for the same
# reason. Skipped here rather than reported, because "you ran the tests we asked
# you to run" is not a finding.
UNMANIFESTED_DIRS = ("build", "__pycache__")


def verify_manifest(root=None):
    """Is this package the bytes that were published? The reviewer's question.

    WHY IT LIVES IN THE BUILDER.  This is the one tool that ships, so it is the
    only place a check can live that a recipient can actually run.  The exporter
    that WROTE `MANIFEST.json` is in the canonical repository and is deliberately
    not in this tree, which is how the README came to offer three verification
    commands that all failed with `[Errno 2]` on a rehearsal.

    WHAT IT PROVES AND WHAT IT DOES NOT.  It proves the tree matches the manifest
    and that the manifest's own `tree_hash` is the hash of its rows -- content and
    layout, self-consistently.  It does NOT prove the manifest is the one we
    published: that is what the git tag and the commit in `provenance` are for.
    A manifest edited together with the file it describes verifies clean here, by
    construction, and saying so is cheaper than implying otherwise.
    """
    root = os.path.abspath(root or ROOT)
    manifest_path = os.path.join(root, "MANIFEST.json")
    if not os.path.isfile(manifest_path):
        raise BuildError(
            "no MANIFEST.json at %s -- --verify-manifest checks THIS package "
            "against its own manifest, so run it from the export root." % root)
    with open(manifest_path, "r") as handle:
        manifest = json.load(handle)
    rows = manifest["files"]
    expected = {row["path"]: (row["bytes"], row["sha256"]) for row in rows}

    found = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in UNMANIFESTED_DIRS)
        for name in sorted(files):
            path = os.path.join(base, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if rel == "MANIFEST.json":
                continue  # It cannot hash itself; see the README's counts.
            found[rel] = (os.path.getsize(path), digest(path))

    missing = sorted(set(expected) - set(found))
    extra = sorted(set(found) - set(expected))
    wrong = sorted(rel for rel in set(expected) & set(found)
                   if found[rel] != expected[rel])
    # The formula, recomputed rather than trusted: `path\0sha256\n` per row in
    # path order, SHA-256 over the lot. The README states it so a reader can do
    # this in four lines of any language instead of taking our word for it.
    recomputed = digest_bytes("".join(
        "%s\0%s\n" % (row["path"], row["sha256"])
        for row in sorted(rows, key=lambda row: row["path"])).encode())

    print("MANIFEST VERIFY %s" % root)
    print("  manifest   %d rows (MANIFEST.json does not hash itself)" % len(rows))
    print("  on disk    %d files, excluding %s"
          % (len(found), " and ".join("%s/" % name for name in UNMANIFESTED_DIRS)))
    checks = [("missing from the tree", missing),
              ("wrong size or hash", wrong),
              ("in the tree and not in the manifest", extra)]
    for label, items in checks:
        print("  %s %-38s %d" % ("ok " if not items else "FAIL", label, len(items)))
        for item in items[:20]:
            print("        - %s" % item)
        if len(items) > 20:
            print("        ... and %d more" % (len(items) - 20))
    stated = manifest.get("tree_hash", "")
    ok_hash = recomputed == stated
    print("  %s tree_hash %s" % ("ok " if ok_hash else "FAIL", recomputed))
    if not ok_hash:
        print("        manifest states %s" % (stated or "nothing"))
    if any(items for _label, items in checks) or not ok_hash:
        raise BuildError(
            "THIS TREE IS NOT THE TREE THE MANIFEST DESCRIBES. Every difference "
            "is listed above. A fresh `git clone` of the published repository "
            "verifies clean; a working copy that has been built in or tested in "
            "should not have differences outside %s."
            % " and ".join("%s/" % name for name in UNMANIFESTED_DIRS))
    print("  RESULT every file in this package matches MANIFEST.json, byte for "
          "byte, and the tree hash is the hash of its rows")
    return manifest


def listing(allow_unrostered=False):
    roster = load_roster()
    print("SOURCE EXPORT BUILD PLAN")
    print("  roster     %s: %d apps + %s, in grid order"
          % (ROSTER_NAME, len(roster["apps"]), roster["launcher"]))
    for app in app_dirs(roster, allow_unrostered=allow_unrostered):
        files = payload_files(os.path.join(ROOT, "apps", app))
        modules = [rel for rel, _abs in files if rel.endswith(".py")]
        assets = [rel for rel, _abs in files if not rel.endswith(".py")]
        note = "  (+4 stock base files, see PATCHES.json)" if app == MENU_DIR else ""
        print("  apps/%-12s %2d modules, %2d assets%s"
              % (app, len(modules), len(assets), note))
    print("  main.py ships as SOURCE (the frozen boot imports it by path)")
    print("  assets/fonts: 1 face here, plus %s from --stock-fonts"
          % " and ".join(sorted(STOCK_FONTS)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--mpy-cross",
                        help="path to mpy-cross; also read from $MPY_CROSS")
    parser.add_argument("--stock-menu",
                        help="the pinned Badgeware release's firmware/apps/menu")
    parser.add_argument("--skip-menu", action="store_true")
    parser.add_argument("--stock-fonts",
                        help="the pinned Badgeware release's firmware/assets/fonts")
    parser.add_argument("--no-stock-fonts", action="store_true",
                        help="accept a /system carrying only MonaSans")
    parser.add_argument("--allow-unrostered", action="store_true",
                        help="compile app directories apps-roster.json does not name")
    parser.add_argument("--verify-mount", metavar="MOUNT",
                        help="compare a mounted badge against build/system/manifest.json")
    parser.add_argument("--verify-manifest", action="store_true",
                        help="hash this package against its own MANIFEST.json")
    parser.add_argument("--manifest",
                        help="the manifest --verify-mount compares against")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.list:
            listing(allow_unrostered=args.allow_unrostered)
            return 0
        # Deliberately before `resolve_mpy_cross`: verifying an install or this
        # package is a read-only hash comparison and needs no compiler at all.
        if args.verify_manifest:
            verify_manifest()
            return 0
        if args.verify_mount:
            verify_mount(args.verify_mount, manifest_path=args.manifest)
            return 0
        mpy_cross = resolve_mpy_cross(args.mpy_cross)
        shared = dict(stock_menu=args.stock_menu, skip_menu=args.skip_menu,
                      stock_fonts=args.stock_fonts,
                      no_stock_fonts=args.no_stock_fonts,
                      allow_unrostered=args.allow_unrostered)
        if args.check:
            check(mpy_cross, **shared)
            return 0
        build(os.path.abspath(args.out), mpy_cross, quiet=args.quiet, **shared)
    except BuildError as error:
        print("\n%s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
