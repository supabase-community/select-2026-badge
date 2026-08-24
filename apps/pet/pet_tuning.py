"""Every Pet dial, in one file that imports nothing.

The owner tunes by playing, so this module holds constants and nothing else:
it can be edited over Disk Mode and the badge rebooted with no risk of touching
logic.  `pet_model` does `from pet_tuning import *`, so nothing in the model may
shadow a name defined here.

UNITS.  Every continuous stat is an INTEGER in TENTHS of a point, 0..1000, so a
displayed "62%" is the integer 620.  Rates ending `_T` are tenths per hour;
rates ending `_P` are permille of a threshold per hour.  Integers are used
throughout because RP2350 MicroPython builds single-precision floats while
CPython uses double: the browser playground reproduces the device width
deliberately, and a previous Pet build lost a day to health reading 40.03 on one
lane and 40.00 on the other.  With integers the three lanes agree bit for bit.

THE FOUR DECIDED CONSTANTS come first and keep their decided meanings, with one
redefinition recorded in the README: DECAY_PER_HOUR is the health lost per hour
at FULL strain (every need empty), not the rate observed in ordinary play, because
health is now an integrator over the needs rather than a standalone linear decay.

Everything the simulation actually reads is DERIVED from those four, never
hand-copied.  Three of them used to have independently maintained integer twins
further down this file, so editing the decided dial over Disk Mode changed
nothing at all on the badge and only a laptop test noticed.  A dial that does not
move the thing it names is worse than no dial, so the twins are now expressions.
"""

# --------------------------------------------------------------------------
# THE DECIDED DIALS.  Tune these first.
# --------------------------------------------------------------------------

DECAY_PER_HOUR = 50.0     # health/hour at strain 1.0 (every need empty + sick)
FEED_VALUE = 40.0         # health-equivalent DATA restored by the first feed
FEED_WINDOW = 45          # seconds; feeds inside one window halve each time
RESTORE_MINUTES = 5       # wall-clock minutes a project restore takes

# --------------------------------------------------------------------------
# Scale and integration
# --------------------------------------------------------------------------

MAX = 1000                # 100.0 points, in tenths
SIM_STEP_S = 300          # fixed 5-minute integration step
# A neglected pet pauses inside ~11 h (132 steps) and the loop short-circuits on
# pause, so the realistic worst case is far below this guard.  The guard exists
# so a corrupt sim_carry can never spin the CPU at app open.
MAX_SIM_STEPS = 2100

# --------------------------------------------------------------------------
# Clock policy (pet_clock)
# --------------------------------------------------------------------------

MIN_VALID_EPOCH = 1_735_689_600     # 2025-01-01; a display hint only, not a gate
MAX_CATCHUP_S = 7 * 86400           # bounds the step loop; 7 d and 3 wk both pause
BACKWARD_REBASE_S = 48 * 3600       # a baseline this far in the future is a dead RTC

# --------------------------------------------------------------------------
# Health: a derived integrator over the needs
#   strain = (W_DATA*d(data) + W_MOOD*d(mood) + W_WASTE*waste + W_SICK*sick)
#   d(v)   = 0 above COMFORT, rising linearly to 1.0 at empty
#   rate   = REGEN*(1 - strain) - DECAY*strain
# --------------------------------------------------------------------------

DECAY_T = int(DECAY_PER_HOUR * 10)   # DECIDED DIAL, in tenths/hour: 50.0 -> 500
REGEN_T = 180             # health/hour regained at strain 0
COMFORT_T = 500           # a need at or above this contributes no strain
W_DATA = 450              # permille; the four weights sum to exactly 1000
W_MOOD = 50
W_WASTE = 200
W_SICK = 300
LOW_HEALTH_T = 350        # the Ant walks on at this health and closes in to 0

# --------------------------------------------------------------------------
# DATA (hunger) and FEED
# --------------------------------------------------------------------------

DATA_DECAY_T = 100        # 10.0/hour: full to empty in 10 h, so an 8 h gap is survivable
FEED_VALUE_T = int(FEED_VALUE * 10)   # DECIDED DIAL, in tenths: 40.0 -> 400
FEED_WINDOW_S = FEED_WINDOW           # DECIDED DIAL, seconds
# One cooldown for the WHOLE care ring, not just FEED.  Every ring entry is a
# repeatable commit and REST is a free two-way toggle, so a per-action rate limit
# is what keeps a mashed B bounded in flash writes and in game state alike.
COMMIT_COOLDOWN_MS = 250
FEED_MOOD_T = 50          # every accepted feed is also a small mood gift
FEED_WASTE_P = 250        # four presses in one window make exactly one pile
OVERFEED_SICK_P = 200     # mashing INSERT on a full table has consequences
OVERFEED_WASTE_P = 340

# --------------------------------------------------------------------------
# MOOD and the PLANNER minigame
# --------------------------------------------------------------------------

MOOD_DECAY_T = 40         # 4.0/hour: full to empty in 25 h
PLAY_MOOD_WIN_T = 450
PLAY_MOOD_LOSS_T = 150
PLAY_HEALTH_WIN_T = 30
# A win also TRAINS the creature.  Without this, discipline decays with no
# recovery path a well-behaved pet can ever use, so food refusal eventually
# punishes the most diligent player - which is exactly backwards.
PLAY_DISCIPLINE_T = 100
PLAY_COOLDOWN_S = 600
PLAY_ROUNDS = 3
PLAY_WIN_ROUNDS = 2

# --------------------------------------------------------------------------
# WASTE and CLEAN
# --------------------------------------------------------------------------

WASTE_P_PER_HOUR = 400    # one pile every 2.5 awake hours
WASTE_MAX = 3

# AUTOVACUUM.  Once the floor has been at WASTE_MAX for this many SIMULATED
# seconds, a worker walks on by itself and takes it down to AUTOVACUUM_FLOOR -
# never to zero.
#
# This is not a mercy dial, it is the joke, and it is accurate.  The canonical
# 2am Postgres experience is not "autovacuum did not run"; it is autovacuum
# running and n_dead_tup not going down, because a long-running transaction, an
# idle-in-transaction session or a stale replication slot is holding back the
# xmin horizon.  Postgres 14+ logs exactly that: "N dead row versions cannot be
# removed yet, oldest xmin: ...".  So the safety net arrives, works, and visibly
# fails at the last inch - which is what makes the manual VACUUM FULL still the
# player's job.
AUTOVACUUM_AFTER_S = 3 * 3600
AUTOVACUUM_FLOOR = 1
MISBEHAVE_WASTE_MULT = 2  # an unruly pet makes twice the mess

# --------------------------------------------------------------------------
# SICKNESS and HEAL
#   One pile alone never makes the pet ill (240 < 300 relief); two piles do in
#   about 5.5 h.  So a player who cleans on any visit is never sick.
# --------------------------------------------------------------------------

SICK_WASTE_P_PER_HOUR = 240
SICK_LOWHEALTH_P_PER_HOUR = 120
SICK_LOW_HEALTH_T = 250
SICK_RELIEF_P_PER_HOUR = 300
SICK_WORSEN_HOURS = 3     # severity 1 becomes severity 2, needing two doses
HEAL_HEALTH_T = 150

# --------------------------------------------------------------------------
# FATIGUE and REST.  Sleep is derived from fatigue, never from a wall clock:
# badges power on with wrong clocks and no timezone, so a calendar night would
# put the creature to sleep at a random hour of the real day.
# --------------------------------------------------------------------------

FATIGUE_T_PER_HOUR = 62       # ~16 h awake to exhaustion
FATIGUE_DRAIN_T_PER_HOUR = 100  # ~10 h of sleep from full
REST_MIN_FATIGUE_T = 500      # REST is offered after ~8 h awake
WAKE_PENALTY_FATIGUE_T = 250  # waking above this costs a care mistake
WAKE_MOOD_COST_T = 100
# Waking a creature that has only just gone to sleep is an UNDO, not neglect:
# below this much sleep the wake is free.  Without it, a mistap on REST costs an
# irreversible care mistake and a mashed B can drive the counter to its cap.
WAKE_GRACE_S = 300
SLEEP_NEED_MULT = 250         # permille: needs decay at a quarter rate asleep
SLEEP_DECAY_MULT = 350        # permille: health decays at ~a third asleep
REGEN_SCHEDULED_MULT = 1000   # a planned maintenance window heals fully
REGEN_UNPLANNED_MULT = 600    # an unplanned outage survives but does not heal

# --------------------------------------------------------------------------
# DISCIPLINE, misbehaviour and SCOLD
# --------------------------------------------------------------------------

DISCIPLINE_START_T = 500
DISCIPLINE_DECAY_T = 10
SCOLD_VALUE_T = 200
SCOLD_MOOD_COST_T = 80
MISBEHAVE_MOOD_BELOW_T = 400
MISBEHAVE_DISC_BELOW_T = 300
MISBEHAVE_P_PER_HOUR = 250    # ~4 h of both conditions before it fires
REFUSE_DISCIPLINE_BELOW_T = 400
REFUSE_EVERY_N = 2            # every second press in a window is refused
REFUSE_SAFETY_HEALTH_T = 250  # refusal can never cause an unavoidable pause
REFUSE_SAFETY_DATA_T = 200

# --------------------------------------------------------------------------
# LIFE STAGES.  Age accrues only while ALIVE, from the same elapsed seconds the
# needs use, so a badge with a wrong clock evolves identically.
# --------------------------------------------------------------------------

# EGG, SEED, DEV, BRANCH, STAGING, ADULT.  BRANCH is a new beat at six hours
# and neither of the two later thresholds moved: STAGING is still 12 h and the
# adult is still 36 h, so every promise in the README about them is unchanged.
# At the fast clock this is a visible transformation every three minutes, which
# is worth MORE in a five-minute session than in a three-day one.
STAGE_AGE_S = (0, 300, 10800, 21600, 43200, 129600)
STAGE_COUNT = 6
ADULT_HA_MAX_MISTAKES = 0     # form 0: the flawless run
ADULT_PROD_MAX_MISTAKES = 6   # form 1: normal care; above this, form 2

# --------------------------------------------------------------------------
# CARE MISTAKES.  Defined by the simulation, so they replay identically and need
# no exit hook.  Each timer rearms after it fires.
# --------------------------------------------------------------------------

MISTAKE_NEED_ZERO_S = 3600
MISTAKE_WASTE_FULL_S = 3600
MISTAKE_SICK_S = 7200
MISTAKE_MISBEHAVE_S = 14400
MISTAKE_PAUSE = 3
MISTAKE_MAX = 99

# --------------------------------------------------------------------------
# PAUSE and RESTORE.  Nothing is permanent: a restore keeps the stage and form
# (it is the same project, restored from backup) and only the mistake counter
# remembers.
# --------------------------------------------------------------------------

RESTORE_S = RESTORE_MINUTES * 60
RESTORED_HEALTH_T = 400
RESTORED_DATA_T = 600
RESTORED_MOOD_T = 600

# --------------------------------------------------------------------------
# UI timings (pet_app).  R18: navigation never persists; commits are debounced
# 400 ms and capped at 1000 ms, matching the device-wide standard in ui.py.
# --------------------------------------------------------------------------

POSTER_IDLE_MS = 30000
# A reaction face is VIEW state with a wall-clock life: the creature pulls a
# face for this long after an action and then goes back to its mood.  Nothing
# about it is saved and it never touches the simulation.
REACT_MS = 700
# The Ant's threat tier may not change more often than this, so a health bar
# falling fast on the 120x clock cannot make him strobe between two poses.
ANT_TIER_MIN_MS = 600
TOAST_MS = 1500
NEWS_MIN_AWAY_S = 1200        # under 20 min away, the meters say it all
STAGE_REVEAL_MS = 2000
GAME_REVEAL_MS = 900
IDLE_LIGHTS_MS = 3000         # R22: caselights are rear-facing, so at rest only

# --------------------------------------------------------------------------
# Pause-screen copy.  Our own wording, keeping only the SHAPE of a service
# suspension notice.  No vendor email text is reproduced here or anywhere else.
# --------------------------------------------------------------------------

PAUSE_FROM = "FROM: ANT"
PAUSE_SUBJECT = "PROJECT PAUSED"
PAUSE_LINE_1 = "YOUR PROJECT HAS BEEN"
PAUSE_LINE_2 = "PAUSED DUE TO INACTIVITY"
PAUSE_BUTTON = "RESTORE PROJECT"

# --------------------------------------------------------------------------
# SPEED.  The one dial that turns the three-day pet into the booth toy.
# --------------------------------------------------------------------------

FAST_SPEED = 120              # simulated seconds per REAL second in fast mode
FAST_DEFAULT = 1              # a badge with no creature yet starts FAST

FAST_RESTORE_REAL_S = 20
FAST_FEED_WINDOW_REAL_S = 3
FAST_WAKE_GRACE_REAL_S = 5
FAST_NEWS_MIN_AWAY_REAL_S = 30
FAST_CATCHUP_S = 6 * 3600     # reconstruction cap, in SIMULATED seconds

# THE ATTENTION CLOCK.  The fast world runs only while somebody is actually
# pressing keys; with no input for this long it drops back to real time.
#
# This exists because a badge worn on a lanyard IS an open app.  Measured before
# it: after INIT, with the app merely open and untouched, the creature PAUSED at
# 315 real seconds - so any badge worn for six minutes was a dead database, and
# the only way to keep a pet alive was to press HOME and never play.  The
# optimal strategy was not to play.
#
# One rule fixes both audiences with no mode switch: a stranger at a booth is
# pressing, so they get the whole arc inside two minutes; a worn badge is not,
# so it decays in real time and reaches a genuine neglect pause in about ten
# hours.  REAL mode is unaffected, because its multiplier is already 1.
ATTENTION_IDLE_MS = 20000

SPEED_BY_MODE = (1, FAST_SPEED)
RESTORE_S_BY_MODE = (RESTORE_S, FAST_RESTORE_REAL_S * FAST_SPEED)
FEED_WINDOW_S_BY_MODE = (FEED_WINDOW_S, FAST_FEED_WINDOW_REAL_S * FAST_SPEED)
WAKE_GRACE_S_BY_MODE = (WAKE_GRACE_S, FAST_WAKE_GRACE_REAL_S * FAST_SPEED)
NEWS_MIN_AWAY_BY_MODE = (NEWS_MIN_AWAY_S, FAST_NEWS_MIN_AWAY_REAL_S * FAST_SPEED)
CATCHUP_S_BY_MODE = (MAX_CATCHUP_S, FAST_CATCHUP_S)
