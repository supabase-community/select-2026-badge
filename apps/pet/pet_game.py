"""PLANNER: the three-round, no-timer minigame.  Pure, with an injected RNG.

Two candidate query plans are stacked vertically with a cost beside each; pick
the cheaper one.  Best of three.

WHY THIS SHAPE.  The interaction standard permits a real-time game screen to
rebind the direction keys, but this one does not need the exemption: stacking the
two candidates vertically makes UP/DOWN a legal one-step selector over an integer
(R12), B stays the commit (R7) and A is a permanently drawn QUIT.  There is no
timer at all, so the screen pauses cleanly and quitting mid-round simply forfeits
with no reward and no penalty.

The only randomness in the whole app lives here and is injected, so tests seed it
and the playground's seeded global `random` makes scenarios deterministic.
"""

from pet_tuning import PLAY_ROUNDS, PLAY_WIN_ROUNDS


PLANS = (
    "SEQ SCAN",
    "INDEX SCAN",
    "BITMAP HEAP",
    "HASH JOIN",
    "NESTED LOOP",
    "MERGE JOIN",
    "GATHER",
    "SORT",
    "MATERIALIZE",
    "CTE SCAN",
)


class Planner:
    def __init__(self, random_below):
        """`random_below(n)` returns an int in [0, n)."""
        self._below = random_below
        self.round = 0
        self.wins = 0
        self.cursor = 0
        self.finished = False
        self.won = False
        self.last_correct = -1
        self.rows = None
        self._deal()

    def _deal(self):
        low = 20 + self._below(60)
        high = low + 15 + self._below(90)
        left = self._below(len(PLANS))
        right = (left + 1 + self._below(len(PLANS) - 1)) % len(PLANS)
        cheap = self._below(2)
        if cheap == 0:
            self.rows = ((PLANS[left], low), (PLANS[right], high))
        else:
            self.rows = ((PLANS[left], high), (PLANS[right], low))
        self.cursor = 0
        self.last_correct = -1

    def move(self, delta):
        """UP/DOWN: change exactly one integer by one step, wrapping (R12/R15)."""
        if self.finished or delta == 0:
            return False
        before = self.cursor
        self.cursor = (self.cursor + delta) % 2
        return self.cursor != before

    def commit(self):
        """B: lock the guess in.  Returns the correct row index for the reveal."""
        if self.finished:
            return self.last_correct
        correct = 0 if self.rows[0][1] <= self.rows[1][1] else 1
        self.last_correct = correct
        if self.cursor == correct:
            self.wins += 1
        self.round += 1
        if self.round >= PLAY_ROUNDS or self.wins >= PLAY_WIN_ROUNDS \
                or (self.round - self.wins) > PLAY_ROUNDS - PLAY_WIN_ROUNDS:
            self.finished = True
            self.won = self.wins >= PLAY_WIN_ROUNDS
        return correct

    def next_round(self):
        if not self.finished:
            self._deal()

    def correct_row(self):
        return self.last_correct
