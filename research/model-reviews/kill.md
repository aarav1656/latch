# Kill

The page a judge watches is latch/screen/index.html. It already reads Open from the last HTTP 200. The harness rewrites that file only after the run returns.

API error. urlopen can block 120s of the 3-minute film. A timeout is uncaught, so the page is never rewritten and a reload still says Open. A caught 401 or 429 paints Shut, the assertion box is empty, and the HTTP code is absent. The judge sees the lock open with no reply, or a shut lock that shows no error.

Prose. The promised line is `assert admits(10, 10) is True`. The parser requires a def and drops that sentence, so nothing is stored. After reload the lock is Shut and the assertion box is blank. A function that only calls admits(10, 10) and then `assert True` stays green on the flip, so the lock stays shut.

Boundary already asserted. The flip turns the weak test red and the run stops before the model call. The page shows Mutant still green: no, Shut, and no assertion. The judge sees the control fail, and the lock cannot open.

Guard. On process start, paint Shut. Paint Open only when this run extracted a test that the harness itself saw fail on the flipped operator and pass after restore. On timeout, HTTP error, a missing def, or a weak flip that is already red, paint that reason on the same page and leave it Shut.
