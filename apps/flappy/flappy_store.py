"""Atomic high-score persistence for POOLER.SQL.

THE DANCE MOVED, THE FILE DID NOT.  Temp + flush + sync + rename, the tolerant
reader and the beats-the-record rule all live in `score_sink.py` now, shared by
all five games and vendored by `scripts/sync_ui.py`.  What is left here is this
game's own CONFIGURATION -- its path and its schema -- and the three function
signatures the app and the tests already call.  Nothing about `/state/flappy.json`
changed: same path, same single `high_score` key.
"""

from score_sink import ScoreSink


STATE_PATH = "/state/flappy.json"
SCHEMA = 1

# THERE ARE NO EXTRAS HERE, unlike Snake.  Snake's level prices every row, so
# its record is meaningless without the level that earned it; this game pays one
# query per pipe at every load, so `SERVED 40` means the same thing whoever set
# it and a companion field would be a number with nothing to say.
_SINK = ScoreSink("flappy", STATE_PATH, SCHEMA, "POOLER.SQL")


def load(path=STATE_PATH):
    """Return ``(high_score, plays, status)``.

    Tolerant by construction: a missing file is a badge that has never been
    played, a corrupt one is a badge whose write was interrupted, both read as
    zero and NEITHER deletes anything.  Any dict at ``schema`` 1 is accepted and
    unknown keys are IGNORED rather than rejected -- the rule that lets a future
    build add a field without invalidating every badge's record.  All of that is
    `score_sink.ScoreSink.read`; the reasoning is in that module.

    ``plays`` IS THAT RULE BEING USED (2026-08-29): how many runs of this game
    have been finished, added as a key at SCHEMA 1 so a badge holding a file
    written before the counter existed keeps its high score and counts 0.  The
    number prices every leaderboard row this game submits -- a score is unique in
    the database as ``(badge_id, game, play_number, score)``.
    """
    high_score, _extras, plays, status = _SINK.read(path)
    return high_score, plays, status


def save(high_score, plays, path=STATE_PATH):
    """Write the record so a power cut cannot leave a half-written file.

    ``plays`` IS REQUIRED AND POSITIONAL rather than defaulted, so a call site
    that predates the counter is a loud ``TypeError`` instead of a silent zero.
    A zeroed counter re-mints play numbers the database already holds, and
    ``on conflict do nothing`` answers 200 to every one of them -- the wearer's
    runs would simply stop appearing, with nothing anywhere to notice.
    """
    return _SINK.write(high_score, (), plays, path)[0]


def update_high_score(score, current, plays, path=STATE_PATH):
    """Persist the run: the record when it beats one, the count always.

    Returns ``(high_score, changed)``.  A run that does not beat the record USED
    to write nothing at all, to spare the flash; it writes now because the play
    counter changes on every completed run and has to be durable.  The record
    itself is still only replaced by a run that beat it.
    """
    high_score, _extras, changed = _SINK.commit(score, current, plays, (), (),
                                                path)
    return high_score, changed
