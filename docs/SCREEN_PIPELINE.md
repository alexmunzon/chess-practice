# Screen pipeline: corners -> squares -> move (experiment, 2026-11-16, simulated images only)

Joins three prototypes into one offline pipeline for a chess board shown on a screen, without
editing them. Not wired into the app. Safety rule: never accept a wrong move; when unsure, withhold.

| Stage | Code |
|---|---|
| corners | `native/ScreenBoardVision` binary (built into `/Users/alexmunzon/chess-builds/pipeline-2026-11-15/pipeline/bin/`) |
| rectify | `scripts/recognition/screen_pipeline.py` (homography + bilinear, k x k area average when the board is > 512 px) |
| squares | `occupancy_classifier_v3.py` (default for the CLI and for code that imports the library without calling `set_classifier()`) or `occupancy_classifier.py` (v2, only when asked by name: `--classifier v2` / `set_classifier('v2')`; its blur-gate hole is closed only in v3.1) |
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

## What truth the scorer uses (and the pipeline does not)
- `positionIndex` -> number of start pictures handed to the pipeline (the human says "review ends here").
- True FEN for resets in re-review and self-aware modes (the simulated human), true corners for the
  orientation a human points out when the detector refused it, and everything in scoring.
- Single mode only: rotation picked nearest the TRUE corners (classifier check, not orientation).

## Commands
```sh
python3 -B tests/screen_pipeline.py          # 31 tests, ~30-70 s; renders its own boards (v3 test needs scenes-v2)
python3 -B scripts/recognition/screen_pipeline.py --scenes ROOT --game ID --out DIR [--start-pictures 3]
python3 -B scripts/recognition/evaluate_screen_pipeline.py --scenes ROOT --split smoke2|dev2|dev --out DIR \
  [--classifier v3|v2] [--agree 1,2,2of3] [--self-aware-n 2,4] [--allow-detector-errors]
```
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
