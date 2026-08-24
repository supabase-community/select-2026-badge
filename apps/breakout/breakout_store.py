"""Atomic high-score persistence for VACUUM.SQL.

THE DANCE MOVED, THE FILE DID NOT.  Temp + flush + sync + rename, the tolerant
reader and the beats-the-record rule all live in `score_sink.py` now, shared by
all five games and vendored by `scripts/sync_ui.py`.  What is left here is this
game's own CONFIGURATION -- its path and its schema -- and the three function
signatures the app and the tests already call.  Nothing about `/state/breakout.json`
changed: same path, same single `high_score` key.
"""

from score_sink import ScoreSink


STATE_PATH = "/state/breakout.json"
SCHEMA = 1

_SINK = ScoreSink("breakout", STATE_PATH, SCHEMA, "VACUUM.SQL")


def load(path=STATE_PATH):
    """Return ``(high_score, status)``.

    Tolerant by construction: a missing file is a badge that has never been
    played, a corrupt one is a badge whose write was interrupted, both read as
    zero and NEITHER deletes anything.  Any dict at ``schema`` 1 is accepted and
    unknown keys are IGNORED rather than rejected -- the rule that lets a future
    build add a field without invalidating every badge's record.  All of that is
    `score_sink.ScoreSink.read`; the reasoning is in that module.
    """
    high_score, _extras, status = _SINK.read(path)
    return high_score, status


def save(high_score, path=STATE_PATH):
    """Write the record so a power cut cannot leave a half-written file."""
    return _SINK.write(high_score, (), path)[0]


def update_high_score(score, current, path=STATE_PATH):
    """Persist a run only when it beats the record.

    Returns ``(high_score, changed)``.  A run that does not beat the record
    writes nothing at all -- flash wear is real and a losing run has no reason
    to touch the file.
    """
    high_score, _extras, changed = _SINK.commit(score, current, (), (), path)
    return high_score, changed
