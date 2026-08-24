"""Atomic high-score persistence for Snake.

THE DANCE MOVED, THE FILE DID NOT.  Temp + flush + sync + rename, the tolerant
reader and the beats-the-record rule all live in `score_sink.py` now, shared by
all five games and vendored by `scripts/sync_ui.py`.  What is left here is
Snake's own CONFIGURATION -- its path, its schema, its one extra field -- and
the three function signatures the app and the tests already call.  Nothing about
`/state/snake.json` changed: same path, same keys, same order.
"""

from score_sink import ScoreSink


STATE_PATH = "/state/snake.json"
SCHEMA = 1
# A record set before the level was recorded, or by a file that predates this
# key. Shown as a bare `HIGH nnn` rather than an invented `@1`, because the
# badge does not know which level earned it.
UNKNOWN_LEVEL = 0

# `high_level` IS NOT A SCHEMA BUMP, deliberately.  It is declared as an EXTRA,
# which is the sink's word for an optional companion field: `read` accepts any
# dict whose `schema` is 1 and ignores keys it does not know, so a badge running
# the older build reads a file written by this one and keeps its record, and
# this build reads an older file and reports `UNKNOWN_LEVEL`.  Bumping the
# schema instead would make every existing file invalid and silently wipe the
# owner's high score -- the exact failure the atomic save exists to prevent.
#
# The four newer games declare NO extras, which is why none of them grew a level
# they have no wager for.
_SINK = ScoreSink(
    "snake", STATE_PATH, SCHEMA, "Snake",
    (("high_level", UNKNOWN_LEVEL, 9),),
)


def load(path=STATE_PATH):
    """Return ``(high_score, high_level, status)``."""
    high_score, extras, status = _SINK.read(path)
    return high_score, extras[0], status


def save(high_score, high_level=UNKNOWN_LEVEL, path=STATE_PATH):
    high_score, extras = _SINK.write(high_score, (high_level,), path)
    return high_score, extras[0]


def update_high_score(score, level, current, current_level=UNKNOWN_LEVEL, path=STATE_PATH):
    """Persist a run only when it beats the record, and record its level too.

    The level travels WITH the score and is never written on its own: a run
    that does not beat the record must not relabel the record it failed to
    beat.
    """
    high_score, extras, changed = _SINK.commit(
        score, current, (level,), (current_level,), path)
    return high_score, extras[0], changed
