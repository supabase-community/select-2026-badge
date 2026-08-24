# schedule -- the offline conference agenda: two stage tabs, fourteen sessions, no network

One screen: a scrollable session list for the selected stage, typeset in an 18 pt vector
face. It reads a baked `schedule.json`, preferring a hand-dropped `/schedule.json`
override on the writable root so a wrong room can be fixed on the morning without a
reflash. There is no network code and no time dial: if the clock is not trustworthy the
badge shows the plain agenda and says nothing about time at all.

**Controls.** UP/DOWN move to the previous or next session on this stage, wrapping at both
ends, with no auto-repeat. A/C move between stage tabs. B is deliberately unbound -- it
opened an offline time dial until that was ruled out, and it was not repurposed. HOME
returns to the launcher. The softkey bar ships off; A/C are named by a hint in the tab row
and UP/DOWN by chevrons drawn at the height of the physical buttons.

**Non-obvious.** HIRES 320x240 at a 1.5x UI scale. It carries the one genuinely
unavoidable blocking call in the whole product: `font.load("MonaSans-Medium")`, a 66 KB
read into a fresh 74 KB object that cannot be chunked or deferred. A frame is presented
and captioned immediately before it, and the rear case lights come up to 0.35 to carry the
pause on a channel the panel cannot. There is a second app hiding in the entry file:
`_unavailable()`, an error screen that never returns, because a strict validator at module
scope plus the firmware's fatal-error path meant one bad byte in `schedule.json` was a
modal reset loop on every badge carrying it.
