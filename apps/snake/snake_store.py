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
    """Return ``(high_score, high_level, plays, status)``.

    ``plays`` IS A KEY, NOT A SCHEMA BUMP (2026-08-29), for `high_level`'s own
    reason: `read` accepts any dict at schema 1 and ignores what it does not
    know, so a badge holding a file written before the counter existed keeps its
    record and counts 0.  The number prices every leaderboard row this game
    submits -- a score is unique in the database as
    ``(badge_id, game, play_number, score)``.
    """
    high_score, extras, plays, status = _SINK.read(path)
    return high_score, extras[0], plays, status


def save(high_score, high_level, plays, path=STATE_PATH):
    """Write the record so a power cut cannot leave a half-written file.

    ``high_level`` LOST ITS DEFAULT AND ``plays`` NEVER HAD ONE, so a call site
    that predates the counter is a loud ``TypeError`` rather than a silent zero.
    A zeroed counter re-mints play numbers the database already holds, and
    ``on conflict do nothing`` answers 200 to every one of them -- the wearer's
    runs would simply stop appearing, with nothing anywhere to notice.
    """
    high_score, extras, _plays = _SINK.write(high_score, (high_level,), plays,
                                             path)
    return high_score, extras[0]


def update_high_score(score, level, current, current_level, plays,
                      path=STATE_PATH):
    """Persist the run: the record when it beats one, the count always.

    The level travels WITH the score and is never written on its own: a run
    that does not beat the record must not relabel the record it failed to
    beat, so a losing level-9 run leaves a level-4 record reading 4.

    A LOSING RUN NOW WRITES, where it used to write nothing at all to spare the
    flash: `plays` changes on every completed run and has to be durable. Only
    the record itself is still gated on beating it.
    """
    high_score, extras, changed = _SINK.commit(
        score, current, plays, (level,), (current_level,), path)
    return high_score, extras[0], changed
