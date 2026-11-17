# Mock-glasses frame-age harness (Phase 5 of MOCK_DEVICE_KIT_PLAN.md, 2026-11-16)

**No real latency was measured.** Meta's Mock Device Kit plays a pre-encoded file inside the Simulator with no radio,
so every number below describes the mock and the harness, never real glasses. The live trust decision is unchanged:
every glasses frame is still `.unknownDAT` and can never get a permit. Evidence (outside the repo):
`/Users/alexmunzon/chess-builds/mock-glasses-phase5-2026-11-16/` (`run1..3/`, `run1..3-summary.json`, `mutation-check.txt`).

## Code round 2 (2026-11-17): review fixes for the session value, the counter and the reader

Simulated video on the Mac only, as before. Evidence (outside the repo):
`/Users/alexmunzon/chess-builds/frame-age-method1-2026-11-17/round2/` (`CHECKLIST.md`, `standard/`, `restart/`,
`restart-reused/`, `tables-round2.txt`, `mutate-round2.log`, `remeasure-check.log`). An independent review
(`/Users/alexmunzon/chess-builds/review-frame-age-method1-2026-11-17/`) found the gaps below. Numbers marked
"reviewer" come from that review and were not re-run here; numbers marked "re-measured" come from this round's runs.

**The counter runs out after about 32 minutes.** The 2-symbol counter has 31^2 = 961 values. At one code every 2 s
it is used up after 1,922 s (about 32 minutes). It must never wrap: a wrapped counter repeats codes the log has already
seen, and the reviewer measured that every fresh picture is then refused (20,000 of 20,000, reviewer). At counter 960
the display must end the session and start a new one: a newly drawn session value, the counter back at 0 and an empty
display log. `encode_code` now refuses counter 961 (and any value outside 0..960) and any session value that is not
4 symbols in 0..30, instead of wrapping silently.

**The session value must be drawn again at every restart.** The session value must be drawn anew every time the counter
or the display log restarts, not only once per stream, and in a real app it must come from a cryptographic random
source. The harness draws it from a seeded generator so that runs repeat; that is fine for a simulation and wrong for
an app. The harness now models a restart inside a stream (`--restart-at 50`: 50 s into every stream the video starts
again at frame 0, the log is emptied and a new value is drawn; the stream goes on). Pictures shown before the restart
and judged after it, old ones accepted: 0 of 7261 with a new value; 1536 of 7261 when the old value is kept
(`--reuse-session-on-restart`; 512, 511, 513 per seed; all are 20 s replays) (re-measured, 3 seeds x 33 streams). The
reviewer's simpler model gave 0 of 12,849 and 7,976 of 12,927 (reviewer). The cost: fresh pictures shown before the
restart and judged after it are refused, 376 of 376 (re-measured). With the restart the controls stay at 0 of 38629
old accepted. The restart also resets the 30 s video loop, so the next-code misread (assumption 5) has more first-loop
time to work in: 332 of 915 with restarts against 152 of 922 without (re-measured).

**Forbidden reader design: "keep the last good value".** A reader that returns the last valid code it saw when it cannot
read the current one lets old pictures in. The harness now scores this design on every picture of the standard run
(record field `acceptFallbackReader`; every other count is unchanged). Old pictures accepted: 830 of 70157 with the
fallback against 152 of 70157 with the real reader (all 152 are the residual next-code misread) (re-measured, 3 seeds:
274, 283, 273 of about 23,400 each). Where it bites: one random symbol wrong 150 of 934, counter misread +1 154 of 916
and -1 151 of 897, 20 s replays 82 of 8712, 5 s replays 62 of 8712, previous-stream replays 79 of 8712; controls 0 of
38629 (re-measured). On the synthetic video, seed 1, the harness reproduces the reviewer's 277 of 23,518 exactly
(re-measured); the reviewer's queue model without any replay screen gave 276 of 5,324 (reviewer). The reader must
refuse a picture whose code it cannot read as valid; it must never substitute an earlier code.

**Check-digit pass rates** (check only, session not compared; the expected rate for a random error is 1 in 961):
3-symbol changes 2113 of 2,000,000 (re-measured; reviewer 2,223 of 2,000,000); cyclic shifts by 1 to 7 positions 21 of
20181 (re-measured; reviewer 14 of 20,174); one symbol dropped and the code padded back to 8, 42 of 68907
(re-measured; reviewer 27 of 61,142); random 8-symbol strings 3111 of 3,000,000 (re-measured; reviewer 3,148 of
3,000,000). Every 1- and 2-symbol change, counter +1 or -1, swap of two symbols and wrong length passed 0 times
(reviewer). These rates are why the session value and the rule remain needed: the check digits alone let about 1 in
1,000 badly garbled codes through.

**A live relay of the current screen.** The reviewer relayed the current session's screen with delays of 0.01 to 2.9 s
plus holds: 0 old accepted at every delay (reviewer), because the rule counts age from the code's first display, so a
relay only adds to the measured age. The real gap is assumption 7: a picture whose code band comes from a fresh exposure
while the board comes from an older one is accepted 20,000 of 20,000 times (reviewer).

**Tests** (`tests/mock_glasses_frame_age.py`, 16 tests, 5 new): `encode_code` refuses bad session values and counter
961; session values use all 4 symbols and differ between seeds; one-symbol misreads reach all 8 positions (including
the check digits) and are all refused; a restart needs a new session value (0 accepted) and keeping the old one is
caught (84 of 404 on the test run); the fallback reader is measured. The check-digit "can fail" probe now requires at
least 10% of +1 misreads accepted when the check is skipped (the test run gives 11 of 53), not just more than 0.
The reviewer's four surviving mutants (session value with only 31 possibilities, the same for every seed, counter 961
accepted, one-symbol misread only in the check digits) are now caught, 4 of 4. Of the reviewer's other 19 faults and
mutants plus 3 new ones for this round, 18 of 21 are caught; the 3 survivors are a stream check bypassed through the
epoch argument (a picture from another stream is still refused by its session value), the sign of c1 flipped (still a
distance-3 code) and `coded_evaluate` ignoring its `verify_session` switch (no harness path turns it off).

**Standard runs unchanged.** Seeds 1-3, 33 streams, without restarts: every judgement is identical to the code round
(103806 of 103806, 103620 of 103620, 103620 of 103620 records equal field by field; re-measured).

## Code round (2026-11-17): session value and check digits in the on-screen code

Simulated video on the Mac only, as in rounds 2-3: nothing here is measured on real glasses, the Simulator or the
app. Evidence (outside the repo): `/Users/alexmunzon/chess-builds/frame-age-method1-2026-11-17/` (`CHECKLIST.md`,
`before/`, `after/`, `drop-session/`, `drop-check/`, `tables.txt`, `mutate.py`, `mutation-results.txt`).

**The code.** 8 symbols from a 31-symbol alphabet: a session value (4 symbols), the counter (2 symbols, here the
video's code index) and 2 check digits, c1 = -(sum of the 6 message symbols) and c2 = -(sum of position x symbol),
both modulo 31. Any two columns of the check are independent, so every change of 1 or 2 symbols is detected; a counter
read as n+1 or n-1 changes at most 2 symbols, so it is always detected. The session value is drawn at random for each
display session (in the harness: once per stream from a seeded generator, and again at every restart when
`--restart-at` is used; a real app must use a cryptographic random source and draw again at every counter or log
restart, see code round 2). The gate refuses a picture unless the check digits hold and the session value equals its own current
one, then applies the unchanged rule (`NonceAgeGate`) to the counter with its own display log. It uses nothing else:
not the scenario, not which pictures are replays. Code: `encode_code`, `read_code`, `coded_evaluate` in
`analyze_frame_age.py`; the Mac harness uses them. `FrameAgeRules.swift` and `FrameAgeHarness.swift` are unchanged
and still use the bare code index.

Chances, by arithmetic (not measured): a valid code of another session passes only if the session values are equal,
1 in 923,521 per pair of sessions; a random 8-symbol string passes the check 1 in 961 and both checks about 1 in 900
million; a single wrong symbol or a neighbouring-counter misread never passes; 3 or more wrong symbols pass the check
about 1 in 961. A reader that returns a complete, different valid code of the same session passes every check.

**Mac results** (seeds 1-3, 33 streams of 100 s each; old = true age over 3.0 s; totals, each seed in
`tables.txt`). "Before" is the round-3 code re-run in this round; it reproduces round 3 exactly. Scenario draws are
the same before and after (the session value and misreads use their own random generators), so rows are paired.

| Scenario | Before: old accepted | After: old accepted |
| --- | --- | --- |
| Controls, all exposures (incl. holds of 30-60 s) | 0 of 38629 | 0 of 38629 |
| Second screen replaying the display 2, 5, 20 s late (same stream) | 0 of 1696, 0 of 8712, 0 of 8712 | same |
| **Second screen replaying the previous stream** | **2033 of 8712** (676, 679, 678 per seed) | **0 of 8712** |
| **Counter misread as the next counter** (before: the whole code +1) | **325 of 1850** (108, 109, 108) | **0 of 916** |
| Counter misread as the previous counter | 0 of 1819 | 0 of 897 |
| One random symbol wrong (new) | not modelled | 0 of 934 |
| Complete valid code of the next counter (new, residual) | (this is the "before" +1 model) | **152 of 922** (53, 49, 50) |

Before, a misread was modelled only as "the whole code +1". After, the misread segments are split 4 ways (counter
+1, counter -1, one random symbol, complete next code), so each after-row has about half the pictures.

Cost, fresh pictures refused: controls 485 of 52988 in the first 30 s of a stream and 112276 of 112276 after the
loop, identical before and after (the code changes nothing for a correctly read picture). All fresh pictures:
155460 of 215358 before, 157132 of 215358 after; the 1672 extra are all in misread segments, where a misread code
is now refused even when the picture is fresh (wanted).

**The harness can still fail.** With one session value for every stream (`--drop-session-value`) the previous-stream
replay is back to 2033 of 8712 (676, 679, 678 per seed). With the check digits skipped (`--drop-check-digits`) the
counter +1 misread is back to 157 of 916 (50, 52, 55), and one random symbol wrong lets 1 of 934 through. The complete
next-code misread stays at 152 of 922 in every run: no check digit can see it. The new tests pin all three (they run a
6-stream synthetic version) and fail on the round-3 code. Faults and mutants (`mutate.py`, each runs the full test file on a changed copy): faults 19 of 20 as expected,
including the 7 new ones (session value removed, check skipped, replay shown with the current session value, gate
judging with the picture's own session value, a counter misread that re-encodes the check digits, and each "can fail"
switch disabled). The unexpected one is again the short 2.5 s code cycle with the real rule: the rule stayed safe (0
of 4386 old accepted, no bound below the true age), but the tests' "can fail" probes need the 15-code test video.
Mutants: 34 of 34 caught. The first pass caught 31 of 34; two survivors were test gaps, now closed (the 2-symbol
test did not isolate the check digits; the other-session test changed every session symbol at once) and one was a
mutant that changed nothing (rewritten).

**What this does and does not show.** The zeros above for the replay of the previous stream and for misreads hold by
construction of the code (a session value that differs, a distance-3 check), on a harness that reports non-zero when
either part is removed; more trials add no strength. They say nothing about real glasses. Assumptions that remain:
1. The display log is never later than the moment a code becomes visible (unchanged).
2. Log and judge share one clock (unchanged).
3. Narrowed: no second source shows a code of the *current* session. A replay of an earlier session is refused unless
   its session value equals the current one (1 in 923,521 per earlier session; the app must draw it with a
   cryptographic random generator, the harness uses a seeded one), and only if the value is drawn again at every counter
   or log restart (code round 2: kept across a restart, 1536 of 7261 old pictures accepted). A live relay of the
   current screen only adds age and was refused at every delay the reviewer tried (0.01-2.9 s); the real gap there
   is assumption 7.
4. Each picture is assigned to the stream it was captured in (unchanged).
5. Narrowed: the reader never returns a complete, different valid code of the current session (all 8 symbols
   consistent). 1-2 wrong symbols are always refused; 3 or more pass the check about 1 in 961. Forbidden design: a
   reader that keeps the last good value and returns it when it cannot read the current code (code round 2: 830 of
   70157 old pictures accepted, against 152 of 70157 for a reader that refuses).
6. Exposure plus rolling-shutter time stays within the margin (unchanged).
7. Board and code are in the same exposure (unchanged). Broken, it lets every old board in: code from a fresh exposure,
   board 3.5-60 s old, 20,000 of 20,000 accepted (reviewer).
8. The log keeps the first display of each code (unchanged).
9. New: the screen can show and the reader can read the 8-symbol code (about 40 bits) as one unit. Today's code band
   carries 8 data bits plus a CRC-8; the harness assumes a picture reads the full code of the display frame the
   project's reader decoded, and does not model blends of the extra symbols. Not built or measured.

The counter still repeats every 30 s in the pinned video, so after the loop every fresh picture is still refused.
With a real 961-value counter the same happens after about 32 minutes unless the session restarts (code round 2).

## Rounds 2-3 (2026-11-17): method 1 re-checked on simulated video on the Mac

Simulated video on the Mac only: no Simulator, no Meta code, no real glasses. Evidence (outside the repo):
`/Users/alexmunzon/chess-builds/frame-age-round2-2026-11-17/` and its `round3/` folder. Real glasses are still
needed before any of this says anything about real frame age.

**The 3 Phase 5 misses are explained by the harness (about 85% confidence, independent review).** They reproduce
exactly: run 2 frames 296, 476 and 656 (codes 5, 8, 11; held 3.101, 3.126, 3.127 s). Two things combined:
- The harness's modelled display log ("code N shown at stream start + 2 s x N") was 209.6-231.1 ms later than the
  first picture showing each code (231.1, 209.6, 209.9 ms in runs 1-3; 22 of 27 codes per run over the 0.05 s
  margin), so held frames looked younger than they were.
- Each missed frame is a single out-of-order mock frame: it shows the next code about 0.13 s before that code's
  timestamp slot, and the 2 frames after it show the old code again. The mock did this 50, 57 and 57 times in
  runs 1-3; the 3 misses are the cases where a 3.1 s hold landed on such a frame.
Not ruled out: that frame is a misread to the next valid code rather than a real early frame; both cause the same
miss. With a log taken from the first picture showing each code ("readback log"), the 3 frames get bounds of
3.151, 3.176 and 3.177 s and are rejected.

**What the zero counts mean.** With a log that is never later than the first picture showing a code, the rule's
bound is at least the true age plus the margin minus the exposure overlap, by construction. In the re-judged
Phase 5 runs the smallest gap between bound and hold is exactly 0.050 s in all 3 runs; in the Mac harness every
bound (control scenarios, exposure up to 50 ms) is at least 0.0397 s above the true age. So "old frames rejected
162 of 162" (re-judged runs) and "0 old accepted" in the Mac control scenarios are a consistency check of the rule,
its Python copy and the harness. They are not evidence about real glasses, and more trials add no strength. Only
the probes below, which break an assumption on purpose, can make method 1 fail.

**Assumptions real glasses must satisfy** (a broken one breaks the guarantee):
1. The display log is never later than the moment a code becomes visible (refresh, panel lag).
2. Log and judge share one clock.
3. No second source shows the same code (a replayed screen or an earlier session breaks it).
4. Each picture is assigned to the stream it was captured in.
5. The reader never misreads to another valid code.
6. Exposure plus rolling-shutter time stays within the margin.
7. Board and code are in the same exposure.
8. The log keeps the first display of each code.

**Harness changes.** `analyze_frame_age.py` measures the display-log error (`harnessTiming`) and refuses to score
method 1 and the combined row when it exceeds the margin (old counts kept under `recordedNotScored`); it also
re-judges with the readback log. Its Python copy of the rule agrees with the recorded Swift verdicts on 4914 of 4914,
5473 of 5473 and 5474 of 5474 frames and polls, and with the compiled Swift rule on 407 of 407 random and edge cases.
`frame_age_mac_sim.py` derives every time from a frame counter on one virtual clock, so machine load cannot change
it. It shows the pinned video at 30 fps (900 of 900 codes decoded with the project's reader). A camera with random
phase and drift exposes 8, 33 or 100 ms; a picture spanning a code change is a real pixel blend. Delivery takes
30-120 ms. Truth = judge time minus the moment the shown content was on screen. Every picture is scored, including
those after the 30 s video loop. Its self-check compares the display log with the true first display of each code:
0.000 ms over 495 codes per run (before, in the Simulator harness: 209.6-231.1 ms). A deliberate 0.23 s log lag
reads 230 ms, the harness refuses to score (exit 3); its unscored counts show 17 of 8452 old pictures accepted and
bounds up to 0.19 s below the true age.

**Mac results** (3 seeds x 33 streams of 100 s, about 104,000 judgements per seed; old = true age over 3.0 s):

| Scenario | Old picture accepted as fresh |
| --- | --- |
| Controls (held 0.1-10 s, queues, bursts, drops, repeats), 8 ms and 33 ms exposure | 0 of 24908 |
| Same controls, 100 ms exposure | 0 of 13721 |
| Holds of 30, 32, 45, 60 s (longer than the 30 s code cycle) | 0 of 2178 each |
| Controls after the video loops (codes repeat) | 0 of 27724 |
| Second screen replaying the display 2, 5, 20 s late (same stream) | 0 of 1696, 0 of 8712, 0 of 8712 |
| **Second screen replaying the previous stream** | **2033 of 8712** (2033 of 2437 in the first 30 s of a stream) |
| **Reader returns the next code (+1)** | **325 of 1850** (325 of 514 in the first 30 s) |
| Reader returns the previous code (-1) | 0 of 1819 |

The two bold rows are findings about the method, not harness bugs. A replayed earlier session shows codes that the
current display has also shown, so method 1 needs codes that never repeat across sessions (for example a session
number in the code). A misread to a newer code under-states the age, so the reader must never return a wrong valid
code. The 100 ms row holds only because the project's reader reports a new code once the picture is mostly new: a
picture showed a code at most 31.5 ms before the log (under the 50 ms margin); a reader that reports earlier would
break it (assumption 6).

Costs (controls): fresh pictures refused 485 of 52988 in the first 30 s of a stream (unreadable blends at code
changes) and 112276 of 112276 after the loop (repeated codes, fail closed). Held pictures still under 3 s accepted
only 7022 of 37457, because a 2 s code slot makes the bound up to 2 s too high.

Unscored pictures: in Phase 5, old pictures after the 30 s loop were left out of method 1's score (20 per run,
none accepted); the round-2 Mac run did the same. Round 3 scores them.

**Tests and fault checks.** `tests/mock_glasses_frame_age.py` recomputes truth from the raw times of every judgement,
reads the limit and margin from `FrameAgeHarness.swift` rather than from the harness, and compares the Python rule
with the Swift rule. The reviewer's 13 faults, adapted to this harness:
12 of 13 as expected. The 10 real bugs were caught (limit changed for rule only or for rule and truth, margin 0, log off
by one code, reader +1, log stamped at delivery, truth from delivery, latest-display log with normal and short code
cycles, reader reading the newer code at 100 ms). Two controls passed as they should: a newer-code reader at 8 ms only,
and 32 s holds only. The unexpected one is the short 2.5 s code cycle with the real rule. The rule stayed safe (0 old
accepted, no bound below the true age), but the tests failed because they expect the two weakness probes to find
misses on the 15-code test video, and with a 2.5 s cycle they find none. Mutants: 19 of 19 caught, including the 3
that survived before (`<` for `<=`, stream check removed, truth from delivery). Details in `round3/mutation-results.txt`.

`FrameAgeHarness.swift` was not changed or re-run (no Simulator this round). Before any new Simulator run, replace
its modelled log with the readback log.

## Verdict, Phase 5 (3 Simulator runs, about 4 minutes each; method 1 row explained in rounds 2-3)

None of the three methods rejected 100% of injected stale frames in the mock. Each fails in the way the plan predicted.

| Method (age limit) | Stale frames rejected | Fresh frames wrongly rejected (steady state) | Where stale frames got through |
| --- | --- | --- | --- |
| 1 Nonce (3.0 s, margin 0.05 s) | 159 of 162 | 103 of 3411 (90 of 3038) | 3 frames held 3.10-3.13 s (run 2), age bound 2.94-2.97 s |
| 2 Offset, 10 s window (excess 0.25 s) | 2861 of 3407 | 193 of 7294 (0 of 4483), all warm-up | delay present from stream start 183 of 366; 1.2 s queue longer than window 363 of 1260 |
| 2 Offset, whole-stream minimum | 3224 of 3407 | 193 of 7294 (0 of 4483), all warm-up | delay present from stream start 183 of 366 |
| 3 Budget + liveness (limit 1.0 s, budget 0.5 s placeholder, gap 0.3 s, 2 agreeing frames) | 674 of 2190 | 756 of 7294 (621 of 4483), all waiting for agreement | any delay before the phone receives the frame: 1.2 s queue 1114 of 1260, start delay 276 of 366, 3 s burst 113 of 180 |
| 3 gap watchdog alone (polls, no frame for > 0.3 s) | 459 of 459 polls rejected (0 of 153, 154, 152 accepted) | n/a | doff: frames keep arriving, watchdog never fires (57-59 of 60 polls accepted per run) |

Per run, stale rejected: method 1 54 of 54, 51 of 54, 54 of 54; method 2 (window) 852 of 1033, 1004 of 1186, 1005 of 1188;
method 2 (whole) 973 of 1033, 1125 of 1186, 1126 of 1188; method 3 226 of 729, 231 of 730, 217 of 731.
Runs 2 and 3 added in-order queues of 0.2 s and 0.3 s. Run loads (1-minute average, start -> end): run 1 6.2 -> 8.3,
run 2 6.4 -> 8.8, run 3 8.8 -> 5.6.

## What "stale" means and how it was injected

The harness app (`native/MockGlassesProbe/FrameAgeHarness.swift`, built by `build_frame_age_harness.py`) streams the
pinned test video (15 frame-index codes, 2 s each, file loops every 30 s) at 720x1280, 30 fps. At each SDK frame
callback it records the time, the timestamp (PTS) and the code, then holds some frames in its own code before the three
rules (`FrameAgeRules.swift`) judge them. Ground truth: hold = judge time - callback time. A frame is stale for a method
when it was held and the hold exceeds that method's age limit. Fresh = never held.

- Downstream: the phone's receipt time is the callback time, then the frame waits (a slow pipeline in the app).
- Upstream: the receipt time is stamped on release (a queue in the radio or SDK that the phone cannot see).
- Scenarios: isolated (every 3rd frame held 0.1, 0.2, 0.3, 0.45, 0.55, 0.95, 1.05, 2, 2.9, 3.1, 5 or 10 s, alternating
  modes); in-order queues of 0.2, 0.3, 0.5, 1.2 s; bursts (held 0.2-3 s, released together); drops (no frames 0.2-3 s);
  frames held 16 s across a fold into the next stream; a 1 s queue from the first frame of a new stream; doff, fold
  and power-off. Polls every 100 ms also ask each rule whether the latest frame is still current.

## Findings per method

**Method 1, nonce.** Readback: 11614 of 11614 frames decoded across 3 runs; 11423 equal the slot implied by the PTS.
The mismatches are the mock showing a code up to 0.134 s before its PTS slot starts. Corruption: 1604 of 1604
unmodified control reads correct; every corrupted variant (one block flipped or grey, 1, 2 or 3 bits flipped in both
copies, heavy noise, blank) abstained 2322 of 2322 times per variant with 0 misreads. The 3 stale accepts come from
the modelled display log: the mock has no real display, so the harness models "code N shown at stream start + 2N",
anchored on the first callback (that anchor was 0.08-0.10 s late). Together with the 0.134 s lead, the log said a code
appeared up to about 0.23 s later than the frames show it, more than the 0.05 s margin. A real display log must never
be later than the moment a code becomes visible, or the margin must cover the error (round 2 measured the log error
at 209.6-231.1 ms; see rounds 2-3 above). Codes repeat after 30 s, and the rule bounds a repeated code by its first display, so all 3883 fresh frames
after the wrap were rejected (fail closed; scored separately). Method 1 also needs codes that change faster than 2 s:
with a 2 s code, the bound of a fresh frame is already up to 2 s.

**Method 2, offset.** Mock timestamps: start at 0 on every new stream, strictly increasing within a stream, advance
1.0005-1.0015 s per second, no change at doff, stream ends at fold and power-off (inverse action alone did not resume;
the new stream restarted at 0 about 6.1-6.3 s after unfold or power-on). Thresholds held exactly: in-order 0.2 s queue
accepted 288 of 300 (12 rejected as out of order where the queue ended), 0.3 s queue rejected 301 of 301 (lowest excess 0.301 s).
Out-of-order late frames are always rejected. It cannot see a delay present from the first frame of a stream
(183 of 366 accepted; the rest fell in warm-up), and with a 10 s window it forgets the fresh minimum during a long queue.

**Method 3, budget and liveness.** Delays inside the app are caught exactly (0 of 162 stale accepted). Delays before
receipt are invisible: with a placeholder budget, frames 1-3 s old are accepted as long as they keep arriving. Its
stale rejects in isolated tests come mostly from the two-frame rule (an old frame shows a different code), which would
not help on a still board. The gap watchdog worked in the mock: no poll older than 0.3 s was accepted after drops,
fold or power-off. It cannot detect doff, because the mock keeps streaming.

## What the mock cannot show

Real radio or Bluetooth latency, clock drift, the glasses' timestamp meaning (Meta issue #347), a real display's refresh
lag, a real queue's shape, Gen 1 behaviour and the budget value for method 3. The mock's own delivery delay is unknown
and is not part of "hold".

## Run it

```sh
P=/Users/alexmunzon/chess-builds/mock-glasses-2026-11-15; O=/Users/alexmunzon/chess-builds/mock-glasses-phase5-2026-11-16
python3 -B native/MockGlassesProbe/build_frame_age_harness.py --frameworks $P/phase1/frameworks --video $P/phase2/replay-14.mp4 --out $O/build
xcrun simctl install 746F2CEB-102D-4CFC-8D11-A5924705537F $O/build/FrameAgeHarness.app
python3 -B $O/run_watch.py run4 250 local.chesscompanion.mockglasses.frameage FrameAgeHarness -- --frame-age
python3 -B native/MockGlassesProbe/analyze_frame_age.py $O/run4/container/Documents/frame-age-report.json
python3 -B tests/mock_glasses_frame_age.py   # no Simulator: 16 of 16 tests since code round 2 (Swift rule checks 38 of 38)
# Rounds 2-3, Mac only (R=/Users/alexmunzon/chess-builds/frame-age-round2-2026-11-17/round3):
python3 -B native/MockGlassesProbe/frame_age_mac_sim.py --epochs 33 --seed 1 --out $R/mac-sim-seed1.json   # seeds 1-3
python3 -B native/MockGlassesProbe/frame_age_mac_sim.py --epochs 33 --seed 1 --display-log-lag 0.23 --out $R/mac-sim-seed1-lag230ms.json  # exit 3
python3 -B $R/mutate.py; python3 -B $R/recorded_checks.py   # faults, mutants; out-of-order frames in Phase 5
# Code round (C=/Users/alexmunzon/chess-builds/frame-age-method1-2026-11-17): seeds 1-3, plus the two "can fail" probes
python3 -B native/MockGlassesProbe/frame_age_mac_sim.py --epochs 33 --seed 1 --out $C/after/seed1.json --records $C/after/seed1-records.json
python3 -B native/MockGlassesProbe/frame_age_mac_sim.py --epochs 33 --seed 1 --drop-session-value --out ...   # or --drop-check-digits
python3 -B $C/tabulate.py; python3 -B $C/mutate.py all   # before/after tables; baseline, faults, mutants
# Code round 2: standard, restart and restart-reused runs (seeds 1-3), tables, mutants, check-digit rates
$C/round2/run_round2.sh; python3 -B $C/round2/compare_tabulate.py; python3 -B $C/round2/mutate_round2.py all; python3 -B $C/round2/remeasure_check.py
```

Network watch (Phase 4b `run_watch.py`: lsof every 0.2 s, nettop every 1 s, system log for Meta host names, DNS, background
transfers and network-extension flows): 0 sockets, 0 DNS queries, 0 flow records and 0 Meta lines in all 3 runs. No system
dialog in any screenshot. Blind spots: a connection shorter than the polls, from a process other than the app, mDNSResponder
or nsurlsessiond, is not ruled out.
