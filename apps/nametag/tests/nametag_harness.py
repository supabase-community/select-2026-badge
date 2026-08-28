"""Fast-lane harness for the wearer's badge app.

Not named `test_*`, so `unittest discover` treats it as a library.

TWO APP DIRECTORIES ARE ON THE PATH, deliberately and in this order: the badge
app's own first, so `import badge_state` and `import nametag` resolve to the
bytes that ship, and identity's second, so a test can reach `identity_model`
and hold the two readers against each other.  Nothing in the badge app imports
anything out of identity's directory -- `test_nametag_app` proves that with an
AST walk -- and this ordering is what makes the pin possible without weakening
it.

`playground/scripts/production-lane.sh` discovers `*/tests` at the repository
root, so this suite joins the fast lane with no wiring at all.

IT ALSO RUNS FROM THE SOURCE EXPORT, AND THAT IS WHY THE PATHS ARE COMPUTED
RATHER THAN WRITTEN DOWN.  `scripts/export-source.py` ships this suite as the
one worked example of how everything else in the repository is verified, into a
`/system`-shaped tree where the app's modules sit BESIDE `tests/` instead of
under `<feature>/badge/nametag/`.  The path calculus below reconstructed the
repository unconditionally until 2026-08-24, so from the export both test
modules failed during COLLECTION -- an outside reviewer ran the suite the README
holds up as proof and got two import errors before a single invariant was
checked.  `LAYOUT` is now discovered, and `gate_included_tests_run` in the
exporter runs this suite from a freshly written export on every build.

WHAT THE EXPORT CANNOT PROVE, named rather than skipped silently.  Three things
this suite pins live outside the shipping tree on purpose: `identity`, the
archived editor whose schema `badge_state` shadows; `scripts/sync_ui.py`, the
vendoring table; and `shared/`, the canonical copies.  The export carries
`shared/` and omits the first two, so `REPO_ONLY` is True there and the cases
that need them skip with that reason printed.  Everything about the SHIPPING app
-- its read-only discipline, its import closure, its staging order, its
resolution seam, its size budget -- runs in both layouts.
"""

import sys
import unittest
from pathlib import Path


TESTS = Path(__file__).resolve().parent
FEATURE = TESTS.parent

# THE ONE DISCRIMINATOR: in the repository the app lives under
# `nametag/badge/nametag/`; in the export `tests/` sits inside the app directory
# itself. Asking the filesystem beats asking an environment variable, because a
# reviewer who copies the tree somewhere else still gets the right answer.
_repository_app = FEATURE / "badge" / "nametag"

if _repository_app.is_dir():
    LAYOUT = "repository"
    APP = _repository_app
    REPO = FEATURE.parent
    IDENTITY = REPO / "identity" / "badge" / "identity"
else:
    LAYOUT = "export"
    APP = FEATURE                       # <export>/apps/nametag
    REPO = FEATURE.parent.parent        # <export>
    IDENTITY = None

# `REPO_ONLY` is the skip condition, and it is deliberately one flag rather than
# a per-test file existence check: a case that needs the archived editor and a
# case that needs the vendoring table are both "this pins the export against the
# repository", and a reader of a skip message should be told that once.
REPO_ONLY = LAYOUT == "export"
REPO_ONLY_REASON = (
    "runs from the repository only: this case pins the shipping app against a "
    "tree the source export omits on purpose (the archived `identity` editor, or "
    "`scripts/sync_ui.py`). The export's own gates cover what ships."
)
requires_repository = unittest.skipIf(REPO_ONLY, REPO_ONLY_REASON)


def sibling_app(name):
    """Another SHIPPING app's directory, in whichever layout this is.

    `setup` is the one this suite reaches for: it is the editor that WRITES
    the state file the nametag reads, and the path pin is asserted against its own
    constant rather than a literal.  Both layouts have it -- `<app>/badge/<app>`
    in the repository, `apps/<app>` in the export -- so this is a path
    translation and not a skip.  Returns None only if the app is genuinely
    absent, which lets a caller skip for a reason it can name.
    """
    for candidate in (REPO / name / "badge" / name, REPO / "apps" / name):
        if candidate.is_dir():
            return candidate
    return None

# Identity first, the app second, so the app's own directory ends up at the FRONT
# of `sys.path`: `import nametag` has to resolve to the bytes that ship, not to
# identity's copy of the same renderer.
for path in ([str(IDENTITY)] if IDENTITY else []) + [str(APP)]:
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)
