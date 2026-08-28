"""Build-time display choices for the production Schedule app."""


USE_HIRES = True

# Design scale on the HIRES canvas, measured against the 12 px `font.sins` line
# this app was originally laid out with. 1.0 reproduces the v1 density; 1.5 is
# the shipping choice — an 18 pt outline face, an 11 px cap, 2.06 mm, 17.7
# arcminutes at 400 mm, which clears the repository's chosen 15 arcminute bar that
# 1.0 sat under at HIRES. Time/speaker metadata derives a 15 pt tier from this
# same dial (10 px cap, 16.1 arcminutes), so there is no independent small-text
# setting to drift below the bar. 2.0 leaves too little room for the agenda.
#
# LORES ignores this dial: it is already pixel-doubled and a pixel font takes
# integer scales only, so 1.5x cannot be expressed there. See
# `ScheduleView._select_face`.
UI_SCALE = 1.5

# THE SOFTKEY BAR SHIPS OFF. Re-measured on the real 13-row Main Stage after the
# two-tier layout, the live landing keeps three readable blocks either way; the
# cost now shows in the whole-stage scroll rather than that one frame:
#
#   False (ships)  list 171 px, 3.24 screens, A/C named in the tab row
#   True           list 145 px, 3.82 screens, A/C in the band, B's slot empty
#
# The band costs 4.875 mm (26 px at HIRES) to restate labels the screen already
# carries: the stage tabs name A and C, the scroll chevrons name UP and DOWN,
# and B is bound to nothing here. So every live key is named with the bar off.
#
# STILL A DIAL AND STILL THE OWNER'S TO SWAP: flip this line and nothing else
# moves. The rule this satisfies is `docs/badge-button-rules.md` §B1 (every
# bound key is named on screen).
SOFTKEYS = False
