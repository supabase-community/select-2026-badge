"""The Settings tile's ONE delete capability, and its whole extent.

A SEPARATE MODULE FOR THE SAME REASON `brightness_store` IS ONE: the model is
drawing-agnostic and I/O-free by contract, the app's `__init__` cannot be
imported by a test (it needs the firmware's injected globals), and a delete path
is the last thing in this tile that should be unit-testable only through a
device. `settings/tests/test_settings_scores.py` drives this file directly.

WHAT IT MAY TOUCH IS THE BOUNDARY, which is the lesson `badgecard`'s reset
records: that app is handed exactly two writers and `test_card_reset` asserts the
SIZE of that set, so "it cannot reach any other file" is structural rather than
careful. This object removes the game records it was constructed with and empties
the undelivered spool. It cannot open, read or write anything else, and the model
it is handed to has no filesystem of its own.

MICROPYTHON. `os.remove` only, no `pathlib`, no f-strings.
"""

import os


class ScoreWipe:
    """Erase the wearer's scores: their high-score records, then the spool.

    NEVER RAISES. It is called from inside `launch()`, where an escaping `OSError`
    reaches the firmware's `fatal_error()` and `machine.reset()` -- so a full
    volume would turn "erase my scores" into a reboot on the exact screen that
    offered the wearer a safe way to do it.

    `wipe()` RETURNS TRUE ONLY IF EVERYTHING IT TRIED SUCCEEDED. A partial result
    is reported as failure because the wearer's copy for it is "some of your
    scores are still here", and a wearer who walked away believing otherwise would
    be wrong in the direction nothing later can correct.

    A FILE THAT WAS NEVER WRITTEN IS ALREADY ERASED. The production roster ships a
    subset of the five games, so a missing record is the NORMAL case rather than
    an error, and counting it as failure would make every honest wipe look
    partial.

    AND THAT CASE IS DECIDED BY THE OBSERVABLE STATE, NOT BY AN ERRNO. This code
    compared `error.args[0]` against a hard-coded ENOENT of 2 until the browser
    lane ran it: the playground's VFS raises **44** for a missing file (WASI's
    numbering, not POSIX's), so all three never-played records counted as
    failures and a completely successful wipe told the wearer `Not all erased`
    every single time. The device's own errno for that case is UNVERIFIED and now
    does not matter -- the promise this makes is "the record is gone", so the
    check is exactly that promise, and it is true on every port.
    """

    def __init__(self, paths, box=None, remove=None, stat=None):
        self._paths = paths
        self._box = box
        self._remove = remove if remove is not None else os.remove
        self._stat = stat if stat is not None else os.stat

    def _present(self, path):
        """Whether the record is still there.  Never raises.

        Only reached on a REFUSED remove, so the common case (a game that was
        never played) pays one `stat` and the happy case pays none.
        """
        try:
            self._stat(path)
            return True
        except Exception:  # noqa: BLE001 - unreadable is as good as gone here
            return False

    def wipe(self):
        ok = True
        for path in self._paths:
            try:
                self._remove(path)
            except Exception as error:  # noqa: BLE001 - a reset is the alternative
                if self._present(path):
                    ok = False
                    print("SETTINGS_SCORES failed={} err={}".format(
                        path, error.__class__.__name__))
        if self._box is not None:
            # THE SPOOL IS LAST, and it is the half that can be absent. A badge
            # with no `/system/lib` has no `scorebox` and therefore no undelivered
            # scores to lose, so its wipe is complete without this step -- which
            # is why `ok` is not forced false when the box is None.
            wiped = getattr(self._box, "wipe", None)
            if wiped is None:
                # An OLDER `/system/lib`: the module is there and the call is not.
                ok = False
                print("SETTINGS_SCORES failed=spool err=predates-wipe")
            elif not wiped():
                ok = False
                print("SETTINGS_SCORES failed=spool err=rewrite")
        return ok
