# Screen pipeline: corners -> squares -> move (experiment, 2026-11-16, simulated images only)

Joins three prototypes into one offline pipeline for a chess board shown on a screen, without
editing them. Not wired into the app. Safety rule: never accept a wrong move; when unsure, withhold.

| Stage | Code |
|---|---|
| corners | `native/ScreenBoardVision` binary (built into `/Users/alexmunzon/chess-builds/pipeline-2026-11-15/pipeline/bin/`); chosen by name, default `original` (see "Corner finder choice" below) |
| rectify | `scripts/recognition/screen_pipeline.py` (homography + bilinear, k x k area average when the board is > 512 px) |
| squares | `occupancy_classifier_v3.py` (default for the CLI and for code that imports the library without calling `set_classifier()`) or `occupancy_classifier.py` (v2, only when asked by name: `--classifier v2` / `set_classifier('v2')`; its blur-gate hole is closed only in v3.1); `occupancy_classifier_v4.py` only by name or as the start fallback (off by default, below) |
| move | `src/core/occupancy-move-inference.js` via `scripts/recognition/occupancy-infer-cli.mjs` (one node process) |

## Per game (the pipeline proper)
Inputs: startFen, the pictures in order, and `start_pictures` = how many leading pictures the human
reviewed as the start (CLI `--start-pictures`, default 1). Nothing else from truth.
1. Start: rectify screen-upright (detector corner 0 = panel top-left, pieces stand as drawn), calibrate
   against startFen's occupancy turned to each of the 4 orientations; accept only if EXACTLY ONE
   calibrates (this fixes a8). Calibrate on the first start picture that passes; every later usable
   start picture must read `unchanged`, a move/ambiguous/no-legal reading rejects the whole start.
2. Later pictures: rotation nearest the last accepted corners (withhold if unclear or not the locked
   one), rectify, classify, labels to a1..h8, `inferMove(trackedFen)` (any unknown -> uncertain).
3. Agreement guard: a move is accepted when AGREE_FRAMES (2) consecutive usable pictures infer the same
   move from the same tracked FEN; others are `pending`. `unchanged`, no-legal, ambiguous or another
   move resets the count; up to 2 unusable pictures (detector, orientation, unknowns) are skipped. Two
   different positions cannot confirm each other: a correct reading of another position gives another
   move or no-legal. AGREE_FRAMES=1 = round 1 (proved: 133 dev numbers identical).
4. `unchanged` keeps the FEN from one picture, but `currentConfirmed` is true only on the picture that
   confirmed a move, a reviewed start picture, or after 2 consecutive `unchanged` readings counted since
   the last accepted move/review. Advice is fresh only while `currentConfirmed` is true.
5. `reviewRequested`: the pipeline asks a human after SELF_REVIEW_AFTER_WITHHELD withheld pictures in a
   row (pending neither counts nor breaks the run) or on a no-legal-explanation reading.
6. Detector crash/non-zero exit/malformed answer = `detector-error` (warning printed), never
   `detector-not-found`. Policy constants and their sha256 are written into every output.

## Start fallback (backup reader at game start; OFF until the v4.3 review approves v4.3)
Setting `START_FALLBACK_CLASSIFIER` in `screen_pipeline.py`, default `None` (off). Turn on with
`set_start_fallback('v4')` or `--start-fallback v4` on either script; `set_start_fallback` returns the old value so a
caller can put it back. Off, the pipeline behaves exactly as the committed code (same records, same policy hash, same
scores; proved below). Leave it off until the independent review of v4.3 approves v4.3.
- **When the backup is asked.** v3.1 (the default reader) always tries the start picture first. Only if v3.1
  calibrates it in NONE of the 4 orientations does v4.3 try the same picture. v4.3 must then calibrate exactly one
  orientation, the same test v3.1 faces. A v3.1 acceptance is never replaced. If v3.1 finds 2+ orientations that fit,
  the backup is not asked: an unclear orientation is a refusal that protects the user. Both refusing is a refusal.
- **Self-check (added after the v4.3 review, 2026-11-16; fallback path only).** The review proved that v4.3's start
  check (`calibrate`) applies none of v4's later-picture rules, so on its own it accepts pictures that are not the
  start: with solid pieces, 66 of 107 such pictures (a piece drawn 6-24 px off its square, an empty start square
  showing a piece-coloured shape, an extra piece under an 80-95 % layer). So after v4.3 calibrates, the pipeline reads
  that same start picture with the new calibration and accepts the start only if all 64 squares come back exactly as
  the stated start (no unknown, no other label); otherwise `startFallback` = `refused-self-check`, with the squares in
  `fallbackSelfCheck`. It applies only to starts that come through the backup: applied to every v4 start it would
  refuse 25 of 109 development starts (review's measurement). v3.1's own starts are unchanged.
- **Who reads the rest of that game: the reader that accepted the start.** Reasons: (1) a reader's calibration is
  learned from the start picture by that reader and is made for that reader only; (2) v3.1 has just refused this
  very scene (on the development data: solid site-style pieces, which v3.1 cannot read), so handing later pictures
  back to it would turn them into withheld pictures, or worse, into readings from a reader that never agreed to this
  board; (3) the agreement guard and "confirmed current" compare pictures of one game with each other, which only means
  something when one reader produced them all. A human re-review keeps the reader. The setting is read once when a
  game's tracker is created, so changing it never changes a running game. The default reader setting
  (`set_classifier`) is never touched by the fallback.
- **What is recorded (only when the fallback is on).** Start records: `startFallback` = `not-needed` (v3.1 accepted),
  `not-tried` (2+ orientations), `accepted`, `refused` or `refused-self-check`; `fallbackRotationsTried`;
  `fallbackSelfCheck` (passed, squares not as stated, examples); `startReader` on an accepted start.
  Every read picture: `reader`. The scorer's game summary: `startReader`; per config and mode: `startsByReader` and
  `startsViaFallback`; the report: `startFallback`. The policy document gains `startFallback` (with v4.3's constants),
  so its hash differs from the default policy's.
- Tests: `StartFallbackTests` in `tests/screen_pipeline.py` (v3.1 accepts and the backup is never asked; v3.1 refuses
  and v4.3 accepts, then v4.3 reads the game, White and Black at the bottom; both refuse; off and v3.1 refuses; 2+
  orientations never reach the backup; the setting is checked and read once per game; scorer counts; the self-check
  refuses a piece off its square, a shape on an empty start square and an extra piece under a layer, each of which
  v4.3's start check alone accepts; the 3 real solid-piece development starts still pass it). The refused
  start is a real one: the scene generator's solid ("flat") pieces, which v3.1 refuses in all 4 orientations and
  v4.3 accepts in exactly the right one. Each test puts the reader and fallback settings back as it found them.

Measured 2026-11-16, with the self-check, on the development splits only (smoke, dev, smoke2, dev2, stressdev; no
held-out split was run). **Simulated pictures, scored on a Mac**; not real screens, not the phone. Default scorer
settings (agree 1 and 2, all three modes). "Wrong moves" = accepted wrong moves (stale "unchanged" excluded; it was 0
everywhere at agree 2), self-aware headline / worst of the three modes. Re-reviews per 100 positions: agree 2,
self-aware. Outputs and scripts: `/Users/alexmunzon/chess-builds/reader-fallback-2026-11-16/round2/` (`runs/`,
`table.txt`, `attack/`); the comparison script is `../compare_runs.py`.

| split | fallback | starts accepted | via backup | wrong moves, 2 pictures | wrong moves, 1 picture | re-reviews/100 positions | ms/picture mean |
|---|---|---|---|---|---|---|---|
| smoke | off | 2 of 2 | - | 0 / 0 | 0 / 0 | 42.86 | 886 |
| smoke | on | 2 of 2 | 0 | 0 / 0 | 0 / 0 | 42.86 | 869 |
| dev | off | 12 of 12 | - | 0 / 0 | 0 / 0 | 42.99 | 682 |
| dev | on | 12 of 12 | 0 | 0 / 0 | 0 / 0 | 42.99 | 683 |
| smoke2 | off | 2 of 2 | - | 0 / 0 | 0 / 0 | 0.0 | 581 |
| smoke2 | on | 2 of 2 | 0 | 0 / 0 | 0 / 0 | 0.0 | 571 |
| dev2 | off | 12 of 12 | - | 0 / 0 | 0 / 0 | 31.45 | 479 |
| dev2 | on | 12 of 12 | 0 | 0 / 0 | 0 / 0 | 31.45 | 482 |
| stressdev | off | 27 of 36 | - | 0 / 0 | 5 / 5 | 20.71 | 474 |
| stressdev | on | 30 of 36 | 3 | 0 / 0 | 5 / 5 | 18.72 | 493 |

- The 3 backup starts are the 3 solid-piece games (`stressdev-style-flat-g0..g2`); all 3 pass the self-check (the
  same counts as before the self-check was added). v4.3 then read 36 positions with 0 wrong moves and 0 re-reviews.
  Still refused with the fallback on: 3 slim "unfamiliar" piece games, 2 lens-distortion games, 1 motion-blur game.
  The 5 one-picture wrong moves are the same mid-move readings with and without the fallback, all in games v3.1
  started; two-picture agreement blocks them. The re-review rate falls only because 36 well-tracked positions were
  added (338 -> 374 positions, 70 re-reviews either way).
- "Off" rows: identical to the committed code (`e482729`) on all 5 splits, reports and every trace compared with
  wall-clock timings left out. The ms column is wall-clock time on a shared, loaded machine; on/off differences in it
  are noise. The backup adds v4.3 work only on start pictures v3.1 refused.

**Start attack through the pipeline** (the v4.3 review's `attack_start.py`, copied unchanged into `round2/attack/`;
each 640x640 picture handed to the real `GameTracker.start` with corners that make the rectification an exact copy of
the board; v3.1 is the default reader). "Before" = fallback on with the self-check removed (private copy).

| style | pictures | fallback off | on, before self-check | on, with self-check |
|---|---|---|---|---|
| solid ("flat") | NOT the start, accepted | 0 of 107 | 66 of 107 (66 by the backup) | 11 of 107 (11 by the backup) |
| solid ("flat") | real start (clean or disturbed), accepted | 0 of 86 | 35 of 86 | 23 of 86 |
| classic | NOT the start, accepted | 55 of 107 (all by v3.1) | 66 of 107 (11 by the backup) | 55 of 107 (0 by the backup) |
| classic | real start (clean or disturbed), accepted | 44 of 86 | 47 of 86 | 46 of 86 |

- **Residual of the self-check:** all 11 flat pictures it still accepts hold an extra piece under a layer of 80 % or
  more in exactly the board colour (a single square at 80-95 %, or a board-coloured "dialog" over four ranks at
  85-92 %): v4.3 reads such a square as empty with confidence. With any tint away from the board colour (6 RGB or
  more) the self-check refuses (12 of 12). Accepting such a start is a wrong start, so this residual stays open until v4.3 itself
  handles it; it is one reason the setting stays off.
- **Cost:** the self-check refuses 12 of 35 disturbed-but-real solid starts that v4.3 alone accepted (glare or shadow
  spots, a faint dark layer on a piece, a cursor, slight banding, a piece nudged 3-4 px); none of the 3 real development starts.
- **Classic boards:** v3.1 itself accepts 55 of 107 classic pictures that are not the start (the same as the review's
  54-55); the fallback adds none of them now. That weakness is v3.1's start check, outside the fallback.
- **Disturbed starts that teach loosened limits (review finding 2, not re-measured here):** of 5 disturbed real starts
  whose calibration made later pictures read wrongly, the review found the self-check refuses 3; 2 of 5 remain.

## Start self-check for the default reader (added 2026-11-17; OFF by default, the owner decides)
Setting `START_SELF_CHECK` in `screen_pipeline.py`, default `False`. Turn on with `set_start_self_check(True)` or
`--start-self-check` on either script; the setter returns the old value. It applies the fallback's self-check to starts
the default reader (v3.1) accepts: after v3.1 calibrates exactly one orientation, it reads the same start picture with
the new calibration and accepts the start only if all 64 squares come back exactly as stated. A refusal has cause
`start-self-check-failed`; it is never handed to the start fallback (`startFallback` = `not-tried`, like an unclear
orientation). With several start pictures a refused first picture lets the next one try, as before. Recorded only when
on: start record `startSelfCheck` (passed, squares not as stated, examples, ms); policy `startSelfCheck` (so the hash
differs); scorer report `startSelfCheck: true`. Read once when a game's tracker is created.
- **Off = unchanged:** on smoke2 the scorer's report and all 12 traces are identical to a copy of the code from before
  the option (wall-clock timings left out). Tests: `StartSelfCheckTests` (off changes nothing and keeps the old record
  layout and policy hash; on refuses a classic start with the e2 pawn drawn 6 or 14 px off its square, which the plain
  check accepts; on still accepts a clean start, White or Black at the bottom, and tracks e2e4; a refused start never
  reaches the fallback; the setting is read once per game). With the refusal line disabled, 3 of the 5 tests fail.

Measured 2026-11-17. **Simulated pictures, scored on a Mac**; not real screens, not the phone. Development splits only
(stressheld and the other held-out splits not run). Outputs and scripts:
`/Users/alexmunzon/chess-builds/start-selfcheck-v31-2026-11-17/` (`logs/`, `runs/`, `scripts/`).

| measure | option off | option on |
|---|---|---|
| classic pictures NOT the start, accepted (review's `attack_start.py`, through `GameTracker.start`) | 55 of 107 | 49 of 107 |
| classic real starts, clean or disturbed, accepted | 44 of 86 | 43 of 86 |
| solid ("flat") and slim ("unfamiliar") pictures, either kind | 0 accepted (v3.1 refuses them all) | 0 |
| good starts smoke2 / dev / dev2 / stressdev | 2 of 2 / 12 of 12 / 12 of 12 / 27 of 36 | the same; no good start newly refused |
| wrong moves accepted, 2-picture rule (worst of 3 modes), all four splits | 0 | 0 |
| wrong moves accepted, 1-picture rule, stressdev (self-aware / worst) | 5 / 5 | 5 / 5 |
| extra time per checked start picture | - | about 120 ms (mean 122, median 112, max 406; 53 development starts) |

- Option-on runs of smoke2, dev, dev2 and stressdev give the same reports and traces as option off, apart from the
  added fields; the option-off baseline for dev, dev2 and stressdev is the 2026-11-16 run in
  `reader-fallback-2026-11-16/round2/runs/`, which today's code reproduces exactly on smoke2.
- **What it catches:** the 6 pictures with the white e2 pawn drawn 6-18 px off its square (v3.1 reads e2 back as
  unknown). **Cost:** 1 disturbed real start, a mouse cursor drawn on the e2 pawn (e2 read back as unknown).
- **What it does not catch (49 of 107):** every remaining picture is one that v3.1's own square reading takes for the
  start, so reading it back agrees with the start check: an extra piece on an empty square hidden under an 80-95 %
  layer near the square's colour (28; v3.1 reads the square empty), an empty start square showing a piece-coloured
  shape (11; read as the expected piece), and the black d7 pawn or a knight shifted 6-16 px (10; still read as on its
  square). The self-check closes the gap between the start check and the reader, not errors of the reader itself, so
  these stay covered only by the person who reviews the start.

## Corner finder choice (added 2026-11-17; default unchanged: `original`)
Two finders, chosen by name with `set_finder(name)` or `--corner-finder` on either script (`FINDERS` in
`screen_pipeline.py`, both binaries in `/Users/alexmunzon/chess-builds/pipeline-2026-11-15/pipeline/bin/`):
`original` = `screen-board-detect` (sha256 `b5774046…`, frozen) and `round2` = `screen-board-detect-round2`, an
unchanged copy of `corner-finder-2026-11-16/round2/bin-new2` (sha256 `3292bcae…`, approved by the round-2 review).
- An unknown name, or a binary that is missing or not executable, is refused (`SystemExit`) and the current finder stays.
  If the chosen binary disappears after it was chosen, every picture becomes `detector-error`: the pipeline never falls
  back to another finder. `set_finder` returns the old name so a caller can put it back.
- With the default the policy document and its hash are unchanged (`37c2ca07…` on smoke2). With `round2` the policy
  gains `cornerFinder` (name and binary sha256), so its hash differs (`2135830b…`).
- Default unchanged, proved: smoke2 scored before and after the change with default settings, 13 of 13 result files
  identical with wall-clock fields removed, same policy hash.
- Tests: `test_corner_finder_default_and_selection`, `test_unknown_corner_finder_is_refused`,
  `test_missing_corner_finder_fails_closed`; `setUp` puts the finder back to `original`. 5 of 5 deliberately broken
  versions of the code (no existence check, no name check, missing binary falls back to the original or to another
  finder, option ignored) each fail at least one of them.

Measured 2026-11-17 on the development splits only (stressheld was NOT scored again). **Simulated pictures, scored on
a Mac** (shared, loaded machine); not real screens, not the phone. Default reader v3.1, default scorer settings.
"Wrong moves" = accepted wrong moves at two-picture agreement, self-aware headline mode (worst of the three modes in
brackets), out of the positions scored. Re-reviews per 100 positions: two pictures, self-aware.

| split | finder | wrong moves, 2 pictures | wrong moves, 1 picture (worst mode) | starts accepted | re-reviews/100 positions | ms/picture mean (detect stage) |
|---|---|---|---|---|---|---|
| smoke2 | original | 0 of 14 (0) | 0 | 2 of 2 | 0.0 | 618 (139) |
| smoke2 | round2 | 0 of 14 (0) | 0 | 2 of 2 | 0.0 | 637 (165) |
| dev | original | 0 of 421 (0) | 0 | 12 of 12 | 42.99 | 525 (134) |
| dev | round2 | 0 of 421 (0) | 0 | 12 of 12 | 42.99 | 721 (192) |
| dev2 | original | 0 of 337 (0) | 0 | 12 of 12 | 31.45 | 440 (118) |
| dev2 | round2 | 0 of 337 (0) | 0 | 12 of 12 | 31.45 | 516 (147) |
| stressdev | original | 0 of 338 (0) | 5 | 27 of 36 | 20.71 | 478 (122) |
| stressdev | round2 | 0 of 338 (0) | 5 | 27 of 36 | 20.71 | 474 (137) |

- No split got worse: the same wrong moves (0 at two pictures), the same starts and the same re-review rate with both
  finders. Corners were identical (within 0.5 px) on every picture both finders found: 48 of 48 (smoke2), 433 of 433
  (dev), 1,047 of 1,047 (dev2), 1,131 of 1,134 (stressdev). The 3 stressdev differences are the 3 start pictures of
  `stressdev-lens-distortion-g2`: round2 refuses them as `board-edges-curved`, the original found corners but the
  reader refused the start anyway, so the outcome is the same.
- Time: the detect stage was 15-58 ms slower per picture with round2 on this loaded machine; total time per picture
  moves with machine load more than with the finder.
- **Lens-distortion limit (round-2 review):** round2 is not a guard against lens distortion. On the review's 422
  two-term-lens pictures it still accepted 24 with corners 5.0-16.6 % off; the original
  accepted 105 of the same 422 with wrong corners (review log `review-corner-finder-round2-2026-11-16/logs/score-round2-sets.txt`,
  copied as `review-lens-sets-copy.txt`). On ordinary pictures in that review both finders: 100 of 100 correct.
  The development splits hold only 3 lens-distortion games, so the table above says little about lenses.
- Outputs, logs and scripts: `/Users/alexmunzon/chess-builds/corner-swap-2026-11-17/` (`runs/`, `table.txt`,
  `corners_diff.txt`, `stressdev_refused.txt`, `runs/compare-before-after-smoke2.txt`, `mutants.log`).

## What truth the scorer uses (and the pipeline does not)
- `positionIndex` -> number of start pictures handed to the pipeline (the human says "review ends here").
- True FEN for resets in re-review and self-aware modes (the simulated human), true corners for the
  orientation a human points out when the detector refused it, and everything in scoring.
- Single mode only: rotation picked nearest the TRUE corners (classifier check, not orientation).

## Commands
```sh
python3 -B tests/screen_pipeline.py          # 48 tests, ~30-90 s; renders its own boards (v3 test needs scenes-v2)
python3 -B scripts/recognition/screen_pipeline.py --scenes ROOT --game ID --out DIR [--start-pictures 3] \
  [--start-fallback v4] [--start-self-check] [--corner-finder original|round2]
python3 -B scripts/recognition/evaluate_screen_pipeline.py --scenes ROOT --split smoke2|dev2|dev --out DIR \
  [--classifier v3|v2] [--agree 1,2,2of3] [--self-aware-n 2,4] [--allow-detector-errors] [--start-fallback v4] \
  [--start-self-check] [--corner-finder original|round2]
```
`--detector PATH` still runs any binary by path; giving it together with a non-default `--corner-finder` is refused.
Held-out splits refuse to run unless `ORCHESTRATOR_HELDOUT_RUN=1`. Exit code 2 = detector errors.

## Scorer
- Configs side by side: agree 1, agree 2, and `2of3` (2 agreeing of any 3 pictures; misreads such as
  no-legal do not reset; measured, not adopted). Three modes each:
  self-aware (HEADLINE: a human only when the pipeline asks; a silently behind tracker stays behind),
  re-review (oracle: reset whenever truth says the tracker is behind), strict (never reset).
- Per picture and per position ("tracked" = the last picture leaves the true FEN, no wrong accept).
- WRONG ACCEPTED = accepted picture whose tracked FEN differs from truth, split into wrong moves and
  stale-unchanged ("nothing moved" while truth moved; also how many were `currentConfirmed`).
- Guard-blocked wrong inferences, agree-2 cost breakdown (reading patterns per lost position),
  withheld by cause, squares confusion, ms per stage, by difficulty/camera/disturbance/move flag.
- FEN comparison skips the en passant field (chess.js writes it only when a capture is legal).

## Limits
- Simulated scenes from one flat piece set; no real screen footage, lens distortion or moire.
- Detection runs batched per game (the detector is stateless per image), not as a live stream.
- Policy set on smoke/dev/smoke2/dev2 only; heldout and heldout2 were scored once by the orchestrator.

## Results (round 3, frozen policy sha256 6626483d...0e6a = v3, agree 2, N 3; simulated images only)
- dev2 self-aware, agree 1 / 2 / 2of3: 0 / 0 / 0 wrong; re-reviews per 100 positions 23.7 / 31.5 / 31.5;
  stale-unchanged 0. All 63 positions agree 2 lost vs agree 1 had only ONE usable picture of 3, so 2of3 = agree 2.
- N chosen on dev2: N=2 tracks every agree-1 position (41.3 re-reviews/100), N=3 cuts that to 23.7.
