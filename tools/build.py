#!/usr/bin/env python3
"""Compile the source export to bytecode and stage the `/system` tree.

THIS FILE SHIPS AS `tools/build.py` INSIDE THE EXPORT, and it is the only script
in there. `scripts/export-source.py` copies it in; it is committed here so it is
tracked, reviewable and gated like everything else.

WHY IT IS NOT `scripts/build_mpy.py`. That script is the canonical builder and it
compiles 28 source trees, including the labs and the archived predecessors this
export does not carry, from paths shaped like `badgecard/badge/badgecard`. The
networking runtime STOPPED being one of the differences on 2026-08-28: it is
three of those 28 trees (`badgelink/badge/badgelink`, `badgelink/badge/realtime`,
`network/vendor/aiohttp`) and it is in this export too, as the one flat `lib/`
described below. The export is shaped like `/system`. Pointing the
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

WHAT IT BUILDS THAT IT DID NOT UNTIL 2026-08-28, AND IT IS THE RADIO. `lib/` is
BadgeLink, the network runtime, and it sits in this package laid out the way
`/system/lib` is rather than the way a source tree is: FLAT modules at the top,
because that directory is flat and `verified_tls` and its neighbours import each
other by bare name; `realtime/` and `aiohttp/` as real package directories,
because their members are called `__init__.py` and `client.py` and only a package
keeps those apart; and the trust anchors under `ca/`, which are NOT modules but
DER bytes `verified_tls` opens by PATH, so they are copied and never compiled.
Every `.py` under `lib/` becomes `/system/lib/<the same path>.mpy` and
`lib/README.md` is documentation that installs nowhere.

AN ABSENT `lib/` IS A CONFIGURATION AND NOT A FAULT, which is why nothing here
raises on one. `apps-roster.json`'s `system_lib.ship` decides whether the export
carries the directory at all, and `main.py` keeps its BadgeLink block either way:
a `sys.path.append("/system/lib")`, which cannot fail on a directory that does
not exist, then an import inside a `try`. So a build with no `lib/` is a working
OFFLINE badge, the report says which of the two it made, and the only thing
refused is the roster and the tree DISAGREEING about which one that is.

WHAT IT REFUSES THAT IT DID NOT USED TO, all three from an outside review:

  1. AN APP DIRECTORY THE ROSTER DOES NOT NAME.  The build used to compile every
     directory under `apps/`, so an accidentally copied lab directory would have
     become a shipping app.  `apps-roster.json` is now the roster and this is a
     refusal.
  2. AN INSTALL NOBODY VERIFIED.  `--verify-mount <MOUNT>` compares a mounted
     badge against the build manifest by size and SHA-256, names stray files and
     AppleDouble sidecars, and exits non-zero. Doing that by hand at roughly 1,000 units
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

AND THE FIFTH THING, WHICH IS WHERE THE ONLY DESTRUCTIVE STEP NOW LIVES.  The
install was four shell lines in the README's copy-paste block, and the delete was
one of them.  Pasted into an ordinary interactive shell with no `set -e` and no
`&&`, every later line ran whether or not the one above it had worked, so a
compile error was followed by `rm -r "$MOUNT/apps" "$MOUNT/assets"`, a copy of the
PREVIOUS build, and a `--verify-mount` against that previous build's own
manifest -- which PASSES, proving only that the wrong bytes copied cleanly.
`--install <MOUNT>` is that procedure as one command, and every check it makes
runs BEFORE the first delete: the build has to exist, match its own manifest, be
built from this tree as it stands now, and not be a degraded one, and `$MOUNT`
has to be a real mounted volume the size of a badge.  A refusal costs the
operator nothing -- the badge is untouched, the build is untouched.

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
    python3 tools/build.py --install /Volumes/Tufty2350   # clear, copy, verify
    python3 tools/build.py --verify-mount /Volumes/Tufty2350
"""

import argparse
import ast
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

# The two root `.py` files the STAGED TREE is allowed to carry as source rather
# than bytecode. `main.py` because the frozen boot imports it by path and it is
# under a kilobyte, so there is nothing to win and a format to get wrong;
# `secrets.py` for the same reason plus a bigger one -- it is the file a
# provisioning step REWRITES, and bytecode is not a thing an operator can edit.
SOURCE_ROOTS = ("main.py", "secrets.py")

# WHICH OF THEM IS COPIED FROM THE TREE, AND `secrets.py` IS NOT ONE OF THEM.
# It was until 2026-08-26, and that was the whole defect: staging copied a root
# `secrets.py` verbatim, the template writer below was guarded by `if not
# os.path.isfile(...)`, so the copy won, and a credential an operator happened to
# leave at the export root shipped as `/system/secrets.py` to every unit of a
# gang-clone. `BUILDING.md` section 2.4 already promised the opposite in print
# ("never populated by anything in this package, ever"), so this is the code
# catching up with the contract, not a new policy.
#
# NOTHING NEEDS THE OTHER BEHAVIOUR. Real values are provisioned to `/secrets.py`
# on the badge's writable root over `mpremote`, never through a build
# (`docs/production-provisioning.md` section 5), and the assembler that merges a
# minted credential refuses any path inside the repository
# (`badgelink/host/assemble_card_e_secrets.py`). So a root `secrets.py` here is
# an accident in every case, and `refuse_source_secrets` stops the build on it.
COPIED_ROOTS = ("main.py",)

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
# `README.md` being in here is also what keeps `lib/README.md` off the badge:
# the network runtime is walked by the same `payload_files` the apps are, so the
# one documentation file in that directory is dropped by the rule that already
# drops every app's, rather than by a second exclusion somebody has to remember.
SKIP_NAMES = ("README.md", "MANIFEST.json", "PATCHES.json")
SKIP_DIRS = ("tests", "shared", "tools", "__pycache__")

MENU_DIR = "menu"
PATCHES_NAME = "PATCHES.json"
ROSTER_NAME = "apps-roster.json"

# The network runtime's directory, and it is the same name on both sides on
# purpose: `lib/<x>` in this package installs as `/system/lib/<x>`. No mapping
# table means none to get wrong, and a traceback on the badge then names a path
# a reader can open in the package they were handed.
LIB_DIR = "lib"

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

# THE CEILING `--install` REFUSES A VOLUME OVER, and it is a sanity bound rather
# than a device measurement, which is why it is 20x rather than 1.1x. A badge's
# Disk Mode volume carries the 12 MB FAT allocation `_stage` budgets against; the
# volume's own total has never been read host-side, so this is set where it cannot
# refuse a real badge and still refuses the mistakes that turn a recursive delete
# into a loss: a home directory, an external disk, a mistyped path on the system
# volume. The identity check that actually carries the weight is `os.path.ismount`.
MAX_VOLUME_BYTES = 256 * 1024 * 1024


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
    """`(rel, abs)` for everything in one payload directory that installs, sorted.

    ONE WALK FOR THE APPS AND FOR `lib/`, and sharing it is the point rather than
    the tidiness: the two rules already in here are the two the network runtime
    needs. `SKIP_NAMES` keeps every `README.md` out of the built tree, `lib/`'s
    included; and the RELATIVE path is preserved, so `realtime/client.py` stays
    inside its package instead of collapsing onto a flat `client.mpy` that
    nothing on the badge can import.
    """
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


def lib_files():
    """The `/system/lib` payload to build: everything under `lib/`, or nothing.

    THE `app_dirs()` OF THE NETWORK RUNTIME -- it answers "what is there to
    build?" and refuses nothing, so the gate that DOES refuse
    (`assert_system_lib_agrees`) can run in `preflight` before a byte is written,
    the same way the roster gate does for the apps.

    AN EMPTY LIST IS A LEGITIMATE ANSWER AND NOT AN ERROR. `apps-roster.json`'s
    `system_lib.ship` decides whether the exporter emits this directory, and
    `main.py`'s BadgeLink block is a `sys.path.append` -- which cannot fail on a
    directory that does not exist -- followed by an import inside a `try`. So a
    package without `lib/` builds a `/system` that boots offline and runs every
    app, which is a shipped configuration rather than a broken one, and raising
    here would turn the owner's own ruling into a failed build.
    """
    root = os.path.join(ROOT, LIB_DIR)
    if not os.path.isdir(root):
        return []
    return payload_files(root)


def source_fingerprint():
    """Every file in this tree that changes what a build emits, as one digest.

    THE STALE-BUILD GUARD, and it is the check `--install` mainly exists for.
    A build that REFUSES leaves the previous `build/system` exactly where it was.
    That is right, and it was itself a fix -- but it means a compile error on file
    140 of 150 used to be followed, in a pasted quick start, by a delete of the
    badge's roots, a copy of the PREVIOUS build, and a `--verify-mount` against
    that previous build's own manifest. All three succeed. The install then proves
    only that the wrong bytes copied cleanly, which is worse than no proof.

    So the manifest records what the build read and `--install` recomputes it: a
    source tree that has moved since the build is a refusal, before the badge is
    touched. It is deliberately TOTAL over `apps/` rather than roster-filtered, so
    a directory that appeared after the build is drift too, and it is deliberately
    content-hashed rather than mtime-compared, because a checkout, a `touch` or a
    clock skew all move an mtime without moving a byte.

    `lib/` IS IN HERE FOR THE SAME REASON `apps/` IS, and it went in the day the
    export started carrying it. The network runtime compiles into the staged
    tree, so editing a module under it moves the bytecode; leaving it out would
    have let `--install` accept a build whose radio code was a version behind the
    tree it claims to have been built from, which is the exact failure this
    fingerprint exists to make impossible for an app.

    Inputs from OUTSIDE the tree -- the four stock launcher files and the two
    stock `.af` faces -- are absent here and do not need to be: `preflight` pins
    all six by SHA-256, so they cannot drift without the build itself refusing.
    """
    rows = []

    def add(rel, path):
        if os.path.isfile(path):
            rows.append((rel, digest(path)))

    apps_root = os.path.join(ROOT, "apps")
    if os.path.isdir(apps_root):
        for app in sorted(os.listdir(apps_root)):
            app_root = os.path.join(apps_root, app)
            if not os.path.isdir(app_root):
                continue
            for rel, abs_path in payload_files(app_root):
                add("apps/%s/%s" % (app, rel), abs_path)
            # `payload_files` skips `PATCHES.json` because it does not INSTALL.
            # It is still a build input: it is the anchor-and-replacement register
            # applied to the stock launcher, so editing it changes the bytecode.
            add("apps/%s/%s" % (app, PATCHES_NAME),
                os.path.join(app_root, PATCHES_NAME))

    # The runtime, through the builder's own staging walk, so what is hashed is
    # what installs: `lib/README.md` is skipped here because it is skipped there.
    for rel, abs_path in lib_files():
        add("%s/%s" % (LIB_DIR, rel), abs_path)

    add(ROSTER_NAME, os.path.join(ROOT, ROSTER_NAME))
    for name in SOURCE_ROOTS:
        add(name, os.path.join(ROOT, name))
    fonts = os.path.join(ROOT, "assets", "fonts")
    if os.path.isdir(fonts):
        for name in sorted(os.listdir(fonts)):
            if name in SKIP_NAMES or name.startswith("."):
                continue
            add("assets/fonts/%s" % name, os.path.join(fonts, name))

    rows.sort()
    return {"files": len(rows),
            "sha256": digest_bytes("".join("%s\0%s\n" % row
                                           for row in rows).encode())}


def load_roster():
    """`apps-roster.json`: the lineup, and the only thing this build compiles.

    THE ROSTER IS A GATE, NOT A HINT.  This build used to enumerate `apps/` and
    compile whatever it found, which means a directory copied in by accident -- a
    lab tile, a comparison harness, a half-finished experiment -- would have
    become a shipping app with an icon on a wearer's grid, silently, at roughly 1,000 units.
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
    if not isinstance(document.get("payload_only", {}), dict):
        raise BuildError("%s has a 'payload_only' that is not an object" % ROSTER_NAME)
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
    # PAYLOAD-ONLY DIRECTORIES ARE ROSTERED AND ARE COMPILED, they are simply not
    # tiles: they hold modules and assets another app reads at runtime and carry
    # no `__init__`, so the launcher's grid scan passes over them. Leaving them
    # out here would make the build refuse the export it was handed.
    named = (list(roster["apps"]) + [roster["launcher"]]
             + sorted(roster.get("payload_only") or {}))
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


def assert_system_lib_agrees(roster, payload):
    """`system_lib.ship` against the `lib/` that is actually in the tree.

    THE DEFECT THIS IS FOR IS THE ONE THE EXPORTER'S OWN COMMENT NAMES: until
    2026-08-28 no code path put the network runtime in the package, so a roster
    reading `ship: true` produced a package with no `lib/` -- and this build
    compiles what is IN THE TREE, so it would have staged a `/system` with no
    runtime while every document in the box said the radio was on. The badge
    boots either way, because `main.py`'s import is guarded, and that is exactly
    why nothing downstream would have caught it: the failure is silent, it looks
    like a clean build, and it is roughly 1,000 units of a wrong claim.

    BOTH DIRECTIONS ARE A STOP, for the reason `app_dirs` refuses a MISSING app
    and a STRAY one rather than only the first: a `lib/` in a tree whose roster
    says the runtime does not ship installs a radio onto badges somebody ruled
    offline, and that ruling is not this build's to overturn quietly.

    AN ABSENT KEY IS NOT A CLAIM, so it is not a disagreement. `ships_system_lib`
    in the release pipeline defaults it to TRUE, which is right for the question
    IT asks ("emit the directory?"); this asks whether a tree and its own roster
    agree, and a roster that never states the key has said nothing to disagree
    with. Older rosters and the minimal ones tests build both land here.
    """
    block = roster.get("system_lib")
    if not isinstance(block, dict) or "ship" not in block:
        return
    modules = [rel for rel, _abs in payload if rel.endswith(".py")]
    if block["ship"] and not modules:
        raise BuildError(
            "REFUSING: %s says the network runtime ships (system_lib.ship is\n"
            "true) and there is no %s/ in this tree with a module in it.\n"
            "This build compiles the tree, so it would stage a /system with no\n"
            "radio while the package's own documents describe a badge with one.\n"
            "The badge would boot -- main.py's import is guarded -- and nothing\n"
            "afterwards would say the runtime was never there.\n"
            "  re-export from a repository whose roster and payload agree, or\n"
            "  set system_lib.ship false if an offline badge is what was meant."
            % (ROSTER_NAME, LIB_DIR))
    if not block["ship"] and payload:
        raise BuildError(
            "REFUSING: %s says the network runtime does NOT ship (system_lib.ship\n"
            "is false) and this tree has a %s/ holding %d file(s).\n"
            "Building it would install a radio onto badges that were ruled\n"
            "offline, and --verify-mount would compare against THIS manifest and\n"
            "call the result verified. Re-export, or flip the roster key\n"
            "deliberately." % (ROSTER_NAME, LIB_DIR, len(payload)))


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


def secrets_template_text():
    """The empty template, generated so it cannot drift from `SECRETS_KEYS`.

    PINNED AT 1,038 BYTES by `export-source.py`'s `EXTERNAL_INSTALLED`, which
    budgets the staged `/system` without building it. Editing this text moves the
    installed total, so the pin moves in the same commit or the export refuses.
    Deterministic: a constant table and no clock.
    """
    lines = [
        '"""Per-unit provisioning slots. EVERY VALUE HERE IS EMPTY.',
        "",
        "Badgeware's frozen `secrets` helper reads `/secrets.py` first and",
        "falls back to this file, so an unprovisioned badge gets empty",
        "strings rather than an ImportError. Provision the per-unit",
        "`/secrets.py` separately; it must be a SUPERSET of these keys.",
        "",
        "THE SHIPPED NETWORK RUNTIME READS THESE SLOTS. Every value is empty.",
        "With empty credentials it stays offline though radio and push start ON.",
        "The fresh local preference is absent by design; this does not connect.",
        "Provision once.",
        '"""',
        "",
    ]
    for key, why in SECRETS_KEYS:
        lines.append("%s = \"\"  # %s" % (key, why))
    return "\n".join(lines) + "\n"


def write_secrets_template(out):
    """Write the template into a staged tree, UNCONDITIONALLY.

    The `if not os.path.isfile(...)` that used to guard this is what let a copied
    root `secrets.py` survive as the shipped file. There is no case in which an
    existing `out/secrets.py` is worth keeping: `out` is a fresh staging
    directory the build owns, and the only correct content is what this function
    produces.
    """
    with open(os.path.join(out, "secrets.py"), "w") as handle:
        handle.write(secrets_template_text())


def assert_secrets_template_empty(out):
    """Re-read the staged template and prove every value empty. Never trust it.

    The same shape as the release pipeline's `secrets-template-empty` gate
    (`scripts/export-handover.py`), and it is here for the same reason: this is
    the ONE artifact whose failure ships a working badge, so a populated value
    must stop the build no matter which code path wrote the file. Parsed rather
    than pattern-matched, because a regex over a credential file is a way to miss
    one, and a build that missed one cannot be taken back off roughly 1,000 badges.

    IT REPORTS KEY NAMES AND NEVER VALUES. A refusal that echoes what it caught
    has moved the credential into a build log, which gets pasted around more than
    the file ever would.
    """
    path = os.path.join(out, "secrets.py")
    if not os.path.isfile(path):
        raise BuildError(
            "REFUSING: the staged tree has no secrets.py. Badgeware's frozen\n"
            "`secrets` helper falls back to it, so a badge without one raises\n"
            "ImportError at boot instead of reading empty strings.")
    with open(path, "r") as handle:
        tree = ast.parse(handle.read(), filename="secrets.py")
    keys = []
    populated = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            keys.append(target.id)
            value = node.value
            if not (isinstance(value, ast.Constant) and value.value == ""):
                populated.append(target.id)
    if populated:
        raise BuildError(
            "REFUSING: %d value(s) in the staged secrets.py are not empty:\n  %s\n"
            "This file installs to /system on every badge. Real credentials go\n"
            "to /secrets.py on the writable root, per-unit, never through a build."
            % (len(populated), "\n  ".join(sorted(populated))))
    expected = [key for key, _why in SECRETS_KEYS]
    if keys != expected:
        raise BuildError(
            "REFUSING: the staged secrets.py keys are not SECRETS_KEYS.\n"
            "  staged   %s\n  expected %s\n"
            "A missing key is a slot the per-unit /secrets.py can silently fail\n"
            "to override." % (", ".join(keys) or "none", ", ".join(expected)))


def refuse_source_secrets():
    """A `secrets.py` at the export root is a STOP, populated or not.

    Checked by existence and never opened, so the refusal cannot read, log or
    diff a credential it was written to protect. Existence is the right test
    anyway: the export ships no `secrets.py` (the exporter's own secrets gate
    refuses one by name), the build generates its own template, and provisioning
    writes `/secrets.py` on the badge over serial -- so there is no legitimate
    way for this file to be here, and "is it populated?" is a question that only
    exists to give a wrong answer once.
    """
    path = os.path.join(ROOT, "secrets.py")
    if not os.path.isfile(path):
        return
    raise BuildError(
        "REFUSING: there is a secrets.py at the export root (%s).\n"
        "This build does not copy it and will not ship it. It emits its own\n"
        "template with every value empty, and a file here would have replaced\n"
        "that template on every badge installed from this tree.\n"
        "  move it OUTSIDE this tree -- do not delete it if it holds anything\n"
        "  real -- then rebuild. Provision the badge separately:\n"
        "    mpremote connect PORT fs cp <file> :/secrets.py.tmp\n"
        "    mpremote connect PORT exec \"import os; "
        "os.rename('/secrets.py.tmp', '/secrets.py')\"" % path)


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

      * there is no `secrets.py` at the export root (a stat, so it is first);
      * the compiler resolves and emits the pinned mpy MAJOR format version;
      * `apps-roster.json` parses and names `apps` and `launcher`;
      * every rostered app directory exists, and no unrostered one does;
      * every rostered app has at least one file to install;
      * `lib/` and the roster's `system_lib.ship` agree about the network
        runtime, in both directions (a package that CLAIMS a radio and carries
        no `lib/` builds a badge that boots and is silently offline);
      * the four stock launcher files exist, hash to their pins, and every
        patch anchor in `PATCHES.json` is present in the bytes it patches;
      * both stock `.af` faces exist and hash to their pins, or the build was
        told out loud to ship one face.

    It returns the validated inputs, so nothing is read or hashed twice: the
    patched launcher bytes and the verified font paths come back with it.
    """
    # FIRST, ahead of even the compiler probe: it is one stat, and it is the only
    # refusal in this list whose failure mode is a credential on roughly 1,000 badges
    # rather than a build that did not happen.
    refuse_source_secrets()

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

    # A stat and a walk, so it is cheap and it is here rather than in `_stage`:
    # the whole reason this function exists is that a refusal must not arrive
    # after the previous good `/system` has been renamed aside.
    assert_system_lib_agrees(roster, lib_files())

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
    `out`.  A refusal anywhere -- a stray `.py`, a tree over the 12 MB `/system`
    budget, a compiler failure on file 140 of 150 -- therefore leaves the last
    good build exactly where it was.  It used to delete first and refuse later,
    which is how an operator ended up with no `/system` at all over an argument
    they could have fixed in a second.

    THE SWAP IS TWO RENAMES, NOT A DELETE AND A RENAME, and the difference is the
    reason this paragraph is here.  This docstring claimed the previous output was
    removed "at the very end, one `os.replace` from the finished tree" while the
    code ran `shutil.rmtree(out)` and THEN `os.replace` -- a window of one
    recursive delete over a ~200-file tree in which the previous build was gone
    and the new one was not yet there.  Ctrl-C, a full disk or a crash inside that
    window left no `build/system` at all, which is precisely what staging exists
    to prevent, and `--install` now depends on `build/system` being either the
    last good build or the new one.  So the old tree is renamed ASIDE first, the
    staged tree is renamed INTO place, and only then is the old one deleted.  The
    honest guarantee, which is what this is: nothing is ever recursively deleted
    while `out` is missing, an interruption between the two renames leaves the
    previous build intact under a `.build-previous-*` sibling, and a failure of
    the second rename puts it straight back.
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

    aside = None
    if os.path.isdir(out):
        # A HOLDER DIRECTORY, then a rename into it. `tempfile.mkdtemp` gives a
        # name nothing else can take, and renaming `out` INSIDE it avoids the
        # mkdtemp-then-rmdir race that reserving a bare name would need.
        aside = tempfile.mkdtemp(prefix=".build-previous-", dir=parent)
        os.rename(out, os.path.join(aside, "system"))
    try:
        os.replace(staging, out)
    except BaseException:
        if aside is not None:
            os.rename(os.path.join(aside, "system"), out)
            os.rmdir(aside)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if aside is not None:
        shutil.rmtree(aside, ignore_errors=True)
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

    # THE NETWORK RUNTIME. `lib/<x>.py` becomes `/system/lib/<x>.mpy` and the
    # relative path is preserved, so `realtime/client.py` stays inside its
    # package instead of collapsing onto a flat `client.mpy` nothing can import.
    # The `ca/` anchors are DER bytes `verified_tls` opens by path, not modules,
    # so they take the copy branch like any other asset. An absent `lib/` is a
    # configuration and not a fault: `lib_files()` returns nothing, this loop
    # does not run, and the badge boots offline behind `main.py`'s guarded
    # import. The report says which of the two was built rather than leaving an
    # operator to infer it from a file count.
    lib_compiled = 0
    lib_copied = 0
    for rel, abs_path in lib_files():
        if rel.endswith(".py"):
            compile_module(mpy_cross, abs_path,
                           os.path.join(out, LIB_DIR, rel[:-3] + ".mpy"),
                           "%s/%s" % (LIB_DIR, rel))
            source_bytes += os.path.getsize(abs_path)
            compiled += 1
            lib_compiled += 1
        else:
            dest = os.path.join(out, LIB_DIR, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(abs_path, dest)
            copied += 1
            lib_copied += 1

    # `COPIED_ROOTS`, not `SOURCE_ROOTS`: `secrets.py` is in the second and not
    # the first, and staging a root copy of it is the defect this split closes.
    for name in COPIED_ROOTS:
        source = os.path.join(ROOT, name)
        if os.path.isfile(source):
            shutil.copyfile(source, os.path.join(out, name))
            copied += 1

    # THE EMPTY TEMPLATE, written rather than copied, and written every time.
    write_secrets_template(out)
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

    # REFUSAL 2b. The stray walk above ALLOWS `secrets.py` by name, so it is the
    # one root file nothing has looked inside. Read it back before it is hashed
    # into the manifest, so a populated value stops the build whatever wrote it.
    assert_secrets_template_empty(out)

    manifest = {
        "schema": "badge-source-export-build/1",
        "target_firmware": TARGET_FIRMWARE,
        # WHAT THE BUILD READ, so `--install` can tell this build from a stale
        # one. Deterministic by construction (a sorted content hash, no clock),
        # because `--check` compares two manifests byte for byte and a timestamp
        # here would make every build look unreproducible.
        "source_inputs": source_fingerprint(),
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
        # SAY WHICH BADGE THIS IS, because the two builds differ only in a
        # directory an operator cannot see from the summary otherwise, and one of
        # them has no radio at all.
        if lib_compiled or lib_copied:
            print("  runtime    BadgeLink: %d module(s) to /system/%s, %d anchor(s)"
                  % (lib_compiled, LIB_DIR, lib_copied))
        else:
            print("  runtime    none: no %s/ in this package, OFFLINE badge"
                  % LIB_DIR)
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
    roughly 1,000 units and was right: every one of those steps is mechanical, and the
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
        #
        # IT NOW POINTS AT `--install` RATHER THAN REPRINTING THE SHELL. Printing
        # `rm -r "<MOUNT>/apps" ...` for an operator to paste is how the delete
        # got separated from its checks in the first place, and this message is
        # read at exactly the moment somebody is about to retry in a hurry.
        raise BuildError(
            "THE INSTALL IS NOT VERIFIED. Equality with the build manifest is "
            "the install's only proof; anything less is a hope.\n"
            "The install manages the whole build, not apps alone -- currently "
            "apps/, assets/, lib/, main.py and secrets.py -- and one command "
            "handles all five paths in the order that is "
            "safe:\n"
            "    python3 tools/build.py --install \"<MOUNT>\"\n"
            "It re-clears the roots, copies the build by name (`build/system/.` "
            "would also install manifest.json, which the build did not emit) and "
            "re-runs this check. Anything listed above that the build does not "
            "emit it will report again rather than delete: removing a file the "
            "build does not own stays the operator's call.")
    print("  RESULT every installed file matches the build, byte for byte, with "
          "no strays")


# ---------------------------------------------------------------------------
# Installing
# ---------------------------------------------------------------------------

# THE TWO KERNEL QUESTIONS THE VOLUME GUARD ASKS, behind names a test can answer
# for. `--install` refuses a `$MOUNT` that is not a real mount point, and a
# unittest cannot create one without root -- so without this seam the guard would
# be the one piece of the install that ships untested, which is the piece it is
# least acceptable to ship untested. The POLICY stays in `assert_badge_volume`
# and under test; only the two kernel answers are substitutable. Nothing else in
# this file is indirected and nothing else should be.
def _is_mount_point(path):
    return os.path.ismount(path)


def _volume_bytes(path):
    return shutil.disk_usage(path).total


def _contains(outer, inner):
    """Is `inner` at or below `outer`? Path text, not the filesystem.

    `os.path.commonpath` and not `startswith`, which reads `/media/Tufty2350x` as
    being inside `/media/Tufty2350`. Both arguments are already absolute.
    """
    try:
        return os.path.commonpath([outer, inner]) == outer
    except ValueError:
        # Different drives on Windows. Nothing can contain anything then.
        return False


def assert_badge_volume(mount):
    """Refuse anything that is not a mounted badge, BEFORE the first delete.

    THE DELETE USED TO HAVE NOTHING IN FRONT OF IT. `rm -r "$MOUNT/apps"
    "$MOUNT/assets"` was pasted straight into the reader's shell, so a `MOUNT`
    that was stale, mistyped or simply never mounted was enough to lose two
    directories -- and any tree holding `apps/` and `assets/` qualified, which
    includes this export's own root.

    `os.path.ismount` is the check that carries this, because it asks the kernel
    instead of reading the path. An unmounted badge leaves `/media/$USER/Tufty2350`
    either absent or an empty leftover directory and neither is a mount point, and
    no directory inside a checkout is ever one. The size ceiling and the
    containment check are cheap seconds: they turn the two mistakes that would
    otherwise cost the most -- pointing at a real disk, pointing at the source
    tree -- into a named refusal rather than a `rm -r`.
    """
    mount = os.path.abspath(os.path.expanduser(mount))
    if not os.path.isdir(mount):
        raise BuildError(
            "REFUSING: --install was given a path that is not a directory:\n"
            "    %s\n"
            "Double-tap the rear RESET button and read the volume name off the "
            "mount before retrying. Nothing has been deleted." % mount)

    # Checked before `ismount` so the operator gets the specific error. This
    # export's root holds `apps/` and `assets/`, which is exactly the shape the
    # old `rm -r` accepted.
    root = os.path.abspath(ROOT)
    if mount == root or _contains(root, mount) or _contains(mount, root):
        raise BuildError(
            "REFUSING: --install was pointed at this source tree, not a badge:\n"
            "    %s\n"
            "The tree holds apps/ and assets/ too, which is the whole reason the "
            "delete is no longer a bare `rm -r`. Nothing has been deleted."
            % mount)

    if not _is_mount_point(mount):
        raise BuildError(
            "REFUSING: %s is not a mount point.\n"
            "A badge in Disk Mode is a mounted volume. An unmounted badge leaves "
            "this path either absent or an empty leftover directory, and a "
            "mistyped path is never a mount point -- so this is the check that "
            "stands between a wrong MOUNT and a recursive delete.\n"
            "Double-tap the rear RESET button, confirm the volume mounted, and "
            "read its name off the mount. Nothing has been deleted." % mount)

    total = _volume_bytes(mount)
    if total > MAX_VOLUME_BYTES:
        raise BuildError(
            "REFUSING: %s is a %s byte volume; a badge is a %s byte FAT "
            "allocation.\n"
            "This is a sanity ceiling, not a device measurement, and it is 20x "
            "the /system budget precisely so it cannot refuse a real badge. A "
            "volume this size is a disk. Nothing has been deleted."
            % (mount, "{:,}".format(total), "{:,}".format(3072 * 4096)))

    if not os.access(mount, os.W_OK):
        raise BuildError(
            "REFUSING: %s is not writable.\n"
            "Checked here rather than discovered halfway through, because "
            "discovering it halfway through means the roots are already gone and "
            "the copy is the thing that failed. Nothing has been deleted." % mount)
    return mount


def install(mount, out=None, allow_degraded=False):
    """The whole install: prove the build, prove the volume, clear, copy, verify.

    ONE COMMAND BECAUSE THE FOUR SHELL LINES IT REPLACES WERE FAIL-OPEN, and
    every one of the four ways that ended badly was confirmed on this tree:

      * NO `set -e` AND NO `&&`. Pasted into an ordinary interactive shell, every
        later line ran whether or not the one above it worked.
      * A FAILED BUILD LEAVES THE PREVIOUS `build/system` IN PLACE -- correct, and
        itself a fix -- so a compile error was followed by a delete of the badge's
        roots, a copy of the STALE tree, and a `--verify-mount` against that stale
        tree's own manifest. It passes. It proves the wrong bytes copied cleanly.
      * A FRESH CHECKOUT HAS NO BUILD AT ALL, so the delete ran, the copy failed,
        the verify failed, and the eject was attempted anyway.
      * NOTHING ASSERTED `$MOUNT` WAS A BADGE before `rm -r`.

    The order below is the whole point: everything that can refuse refuses before
    anything is deleted, so a refusal costs the operator nothing -- badge
    untouched, build untouched, and the message says which of the two to fix.

    IT IS NOT ATOMIC ON THE VOLUME AND MUST NOT CLAIM TO BE. FAT on a USB volume
    has no rename-into-place, so between the clear and the end of the copy the
    badge holds a partial `/system`. That is survivable and always was -- the
    badge is in Disk Mode, not running the tree -- and the recovery is to run this
    command again. What is NOT survivable is ejecting a partial install, which is
    why the verification is the last step and the caller's eject is chained to
    this command's exit code rather than merely printed after it.
    """
    out = os.path.abspath(out or DEFAULT_OUT)
    manifest_path = os.path.join(out, "manifest.json")
    where = os.path.relpath(out, ROOT)

    if not os.path.isfile(manifest_path):
        raise BuildError(
            "REFUSING: there is no build to install.\n"
            "%s/manifest.json does not exist, so there is nothing to clear the "
            "badge FOR. Compile first:\n"
            "    python3 tools/build.py --mpy-cross <path> \\\n"
            "        --stock-menu  <badgeware>/firmware/apps/menu \\\n"
            "        --stock-fonts <badgeware>/firmware/assets/fonts\n"
            "Nothing on the badge has been touched." % where)
    with open(manifest_path, "r") as handle:
        manifest = json.load(handle)

    # 1. IS THE BUILD THE BUILD IT SAYS IT IS? A half-written or hand-edited
    #    `build/system` would otherwise be copied and then verified against its
    #    own manifest, which is a tautology rather than a check.
    expected = {row["path"]: (row["bytes"], row["sha256"])
                for row in manifest["files"] if row["path"] != "manifest.json"}
    staged = tree_index(out)
    staged.pop("manifest.json", None)
    drift = (sorted(set(expected) - set(staged))
             + sorted(set(staged) - set(expected))
             + sorted(rel for rel in set(expected) & set(staged)
                      if staged[rel] != expected[rel]))
    if drift:
        raise BuildError(
            "REFUSING: %s does not match its own manifest (%d file(s) differ, "
            "first: %s).\n"
            "Rebuild before installing. Nothing on the badge has been touched."
            % (where, len(drift), drift[0]))

    # 2. IS IT A BUILD OF THIS TREE AS IT STANDS NOW? The stale-build case above,
    #    and the only one of the four that a careful operator can still walk into
    #    after `set -e` is in place: it survives a build they ran yesterday.
    recorded = manifest.get("source_inputs")
    current = source_fingerprint()
    if recorded is None:
        raise BuildError(
            "REFUSING: %s was written by a build tool that did not record what it "
            "read, so there is no way to tell it from a stale build.\n"
            "Rebuild with this version. Nothing on the badge has been touched."
            % where)
    if recorded != current:
        raise BuildError(
            "REFUSING: %s is STALE -- it was built from a different source tree "
            "(%d files hashing %s; this tree is %d files hashing %s).\n"
            "A build that refuses leaves the previous one in place, so this is "
            "what a failed compile looks like from here. Rebuild, read the "
            "build's output, and install that. Nothing on the badge has been "
            "touched."
            % (where, recorded.get("files", -1), recorded.get("sha256", "?")[:12],
               current["files"], current["sha256"][:12]))

    # 3. IS IT A COMPLETE BUILD? `--skip-menu` and `--no-stock-fonts` each produce
    #    a `/system` that would REGRESS a stock badge, because this tree replaces
    #    `/system` wholesale rather than merging: installing one REMOVES the
    #    launcher or the two stock faces from the badge. The build already says so
    #    loudly; nothing used to stop the install.
    degraded = []
    if manifest.get("menu") == "skipped":
        degraded.append("the launcher (apps/%s)" % MENU_DIR)
    if manifest.get("stock_fonts") == "not supplied":
        degraded.append("the two stock faces (%s)" % ", ".join(sorted(STOCK_FONTS)))
    if degraded and not allow_degraded:
        raise BuildError(
            "REFUSING: %s is a DEGRADED build -- it is missing %s.\n"
            "This tree replaces /system wholesale, so installing it REMOVES those "
            "from the badge, and --verify-mount compares against THIS manifest "
            "and would call the result verified. Rebuild with --stock-menu and "
            "--stock-fonts, or pass --allow-degraded if a partial badge is what "
            "you meant. Nothing on the badge has been touched."
            % (where, " and ".join(degraded)))

    # 4. WAS IT BUILT FOR THE FIRMWARE THIS TOOL PINS? A `.mpy` whose format
    #    version disagrees with the firmware raises at import, and an import that
    #    raises inside `launch()` resets the badge -- every badge, not one.
    if manifest.get("target_firmware") != TARGET_FIRMWARE:
        raise BuildError(
            "REFUSING: %s was built for firmware %r and this tool pins %r.\n"
            "Rebuild. Nothing on the badge has been touched."
            % (where, manifest.get("target_firmware"), TARGET_FIRMWARE))

    mount = assert_badge_volume(mount)

    # THE ROOTS ARE DERIVED FROM THE MANIFEST, NOT TYPED. Two directories today
    # (`apps/`, `assets/`); the day the build emits a third, the clear follows it
    # without anybody remembering to edit a list here. `main.py` and `secrets.py`
    # are files, not roots: the copy overwrites them.
    roots = sorted(set(rel.split("/")[0] for rel in expected if "/" in rel))
    print("INSTALL %s -> %s" % (where, mount))
    print("  build      %d files, tree hash %s"
          % (len(expected), manifest.get("tree_hash", "?")[:12]))
    print("  source     %d input files hashing %s (matches this tree)"
          % (current["files"], current["sha256"][:12]))
    print("  clearing   %s" % ", ".join("%s/" % name for name in roots))
    for name in roots:
        victim = os.path.join(mount, name)
        if os.path.isdir(victim):
            shutil.rmtree(victim)

    # `shutil.copyfile` rather than `cp -R`, and that is the AppleDouble FIX
    # rather than a style preference. On macOS `cp -R` carries a file's extended
    # attributes; FAT cannot hold them, so the kernel writes them beside the file
    # as a `._*` AppleDouble sidecar -- and a sidecar under `apps/` is a file the
    # badge tries to IMPORT. `COPYFILE_DISABLE=1` is the documented way to
    # suppress that, BUILDING.md said so, and neither copy command in the quick
    # start set it. `copyfile` copies bytes and no metadata, so there is nothing
    # left to disable. The sidecar check in `verify_mount` stays regardless: a
    # Finder drag or an earlier hand install can have left one on the volume.
    for rel in sorted(expected):
        destination = os.path.join(mount, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(os.path.join(out, rel.replace("/", os.sep)), destination)
    print("  copied     %d files (manifest.json is the build's proof file and "
          "does not install)" % len(expected))

    # THE VERIFY IS INSIDE THE INSTALL, so it cannot be the step somebody skips
    # when they are in a hurry, and its non-zero exit is what the caller's eject
    # is chained to.
    verify_mount(mount, manifest_path=manifest_path)
    print("  RESULT installed and verified. Eject before resetting, then OPEN AN "
          "APP: an install is not a test.")
    return manifest


# What is legitimately in this package and not in `MANIFEST.json`: the build's own
# output tree, the bytecode CPython writes beside the shipped test suite the
# moment anybody runs it, and `.git/`. The first two are in the emitted
# `.gitignore` for the same reason. Skipped here rather than reported, because
# "you ran the tests we asked you to run" is not a finding.
#
# WHY `.git` IS ON THIS LIST, and it is not optional. This package is DISTRIBUTED
# AS A GIT REPOSITORY: `scripts/publish-dist.py` mirrors it into a standalone
# repo, every publish is a commit stamped `Published-From:`, and `CONTRIBUTING.md`
# invites pull requests -- so a recipient's first act is `git clone`, and the
# README's headline verification is this file's `--verify-manifest`. Without this
# entry the walk below descends `.git/` and reports every object under it as a
# file the manifest does not name (201 of them on a pristine clone, measured
# 2026-08-24), so the one command meant to prove the clone pristine HARD-FAILS on
# it. `.git` was absent until 2026-08-24, and the README's "a fresh git clone
# verifies clean" claim was false against the shipped tree for exactly that
# reason. git cannot ignore its own metadata directory, so `.gitignore` cannot
# carry it; the skip has to live here. `--verify-mount` walks a badge volume
# through `tree_index`, which never consults this tuple and where no `.git` exists
# anyway, so this entry is inert there.
UNMANIFESTED_DIRS = ("build", "__pycache__", ".git")

# These exact root files are operator inputs/outputs beside the public source,
# not part of it. Keep this an explicit allowlist: a suffix/glob would let an
# accidentally renamed credential evade the manifest check. Neither name is in
# SOURCE_ROOTS/COPIED_ROOTS, so the builder cannot stage it into `/system`.
UNMANIFESTED_ROOT_FILES = ("build.zip", "secrets.prod.py")


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
            if rel in UNMANIFESTED_ROOT_FILES:
                continue  # Exact local-only names; close spellings still fail.
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
    ignored = (["%s/" % name for name in UNMANIFESTED_DIRS]
               + list(UNMANIFESTED_ROOT_FILES))
    print("  on disk    %d files, excluding %s"
          % (len(found), " and ".join(ignored)))
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
            % " and ".join(ignored))
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
    parser.add_argument("--install", metavar="MOUNT",
                        help="clear, copy and verify build/system onto a mounted badge")
    parser.add_argument("--allow-degraded", action="store_true",
                        help="install a --skip-menu/--no-stock-fonts build anyway")
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
        # Also before `resolve_mpy_cross`: installing copies an EXISTING build
        # and compiles nothing, so demanding a compiler here would make the one
        # safe install path harder to reach than the unsafe shell it replaced.
        if args.install:
            install(args.install, out=args.out,
                    allow_degraded=args.allow_degraded)
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
