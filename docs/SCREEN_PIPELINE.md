# Screen pipeline: corners -> squares -> move (experiment, 2026-11-15, simulated images only)

Joins three prototypes into one offline pipeline for a chess board shown on a screen, without
editing them. Not wired into the app. Safety rule: never accept a wrong move; when unsure, withhold.

| Stage | Code |
|---|---|
| corners | `native/ScreenBoardVision` binary (built into `/Users/alexmunzon/chess-builds/pipeline-2026-11-15/pipeline/bin/`) |
| rectify | `scripts/recognition/screen_pipeline.py` (homography + bilinear, k x k area average when the board is > 512 px) |
| squares | `scripts/recognition/occupancy_classifier.py` `calibrate` / `classify` (unchanged, thresholds untouched) |
| move | `src/core/occupancy-move-inference.js` via `scripts/recognition/occupancy-infer-cli.mjs` (one long-lived node process, JSON lines) |

## Per game
1. Start frame (stands for the human-confirmed position; labelled "simulated review"): detect
   corners, rectify ONCE in screen-upright order (detector corner 0 = panel top-left, so pieces
   stand as drawn), then `calibrate` against startFen's occupancy turned into each of the 4 possible
   orientations. Accept only if EXACTLY ONE calibrates; otherwise "start rejected" (safe
   abstention). This fixes which corner is a8 (an a8-up panel shows Black-at-bottom pieces upside down).
2. Every later frame: detect; choose the rotation whose corners are nearest the last ACCEPTED
   frame's a8,h8,h1,a1 corners. Withhold ("orientation") if the best mean shift exceeds 25 % of the
   board side or the second-best is not at least 2x further, or if the result differs from the
   rotation locked at the start. A real board moves a fraction of a side between frames; a wrong
   rotation is a whole side away, so the choice is unambiguous or refused.
3. Rectify (screen-upright), classify, turn labels to a8..h1, reorder to a1..h8, `inferMove(trackedFen)`
   (strict: any unknown -> uncertain). `unchanged` keeps the FEN; detector miss, orientation,
   uncertain, ambiguous, no-legal-explanation withhold. Truth is used only for startFen.
4. Agreement guard (`AGREE_FRAMES`, default 2): a `move` is accepted only when that many CONSECUTIVE
   usable pictures each infer the same move from the same tracked FEN; the FEN advances at the
   confirming picture (others are `pending`). An `unchanged`, no-legal, ambiguous or other-move picture
   RESETS the count; up to 2 unusable ones (detector, orientation, unknowns) are skipped (dev2: re-reviews
   46.7 -> 40.1 per 100 positions, 0 wrong either way; `--agree-interruption reset`). Correct readings of two different positions
   cannot agree: the later one gives another move or no-legal-explanation. The residual case (a misread
   that copies the NEXT position) can only confirm the true next move. `AGREE_FRAMES=1` = round 1.
5. Several start pictures: calibrate on the first that passes the 4-rotation test; every later usable
   start picture must read `unchanged`, a move/ambiguous/no-legal reading rejects the whole start.
6. `--classifier v2|v3` (v2 default; v3 imported lazily, clear error if the file is missing).
Policy constants (`POLICY` + the classifier's own) and their sha256 are written into every output.

## Commands
```sh
python3 -B tests/screen_pipeline.py                     # 21 tests, ~25 s, renders its own boards
python3 -B scripts/recognition/screen_pipeline.py --scenes /Users/alexmunzon/chess-builds/pipeline-2026-11-15/scenes \
  --game smoke-g00 --out /Users/alexmunzon/chess-builds/pipeline-2026-11-15/pipeline/traces
python3 -B scripts/recognition/evaluate_screen_pipeline.py --scenes /Users/alexmunzon/chess-builds/pipeline-2026-11-15/scenes \
  --split smoke|dev --out .../eval-<split> [--classifier v2|v3] [--agree 1,2]   # scenes-v2: smoke2|dev2
python3 -B scripts/recognition/evaluate_screen_pipeline.py --single-scenes /Users/alexmunzon/chess-builds/screen-board-2026-11-15 \
  --single-split dev --out /Users/alexmunzon/chess-builds/pipeline-2026-11-15/pipeline/single-dev
```

## Scorer
- Each AGREE_FRAMES value (default 1 and 2, side by side) x two modes. strict: never reset. re-review:
  one-picture roots reset after any withheld picture (round-1 rule); multi-picture roots
  (`positionIndex`) reset at the end of a position whose move was not accepted (one re-review).
- Per picture AND per position: "tracked" = last picture leaves the true FEN, no wrong accept.
- Guard-blocked wrong inferences: pictures whose single-picture `move` was wrong (tracker in sync)
  and never confirmed; listed individually with a debug image.
- WRONG ACCEPTED = an accepted frame whose tracked FEN (placement, side, castling) differs from
  truth: wrong move, `unchanged` when a move happened, `move` on a repeat frame, or any accept
  while behind. Each is listed with misread squares and a rectified debug image.
- Also: correct accepted, withheld by cause, start rejected, games tracked end to end with zero
  re-reviews, re-reviews per 100 frames, per-square confusion vs the true FEN, ms per stage, broken
  down by difficulty, cameraMode, disturbance (type, and none/moving/sticky) and move flag.
- FEN comparison skips the en passant field (chess.js writes it only when a capture is legal).
- Single mode: per-frame classifier check on the old single-position scenes (rotation from TRUE corners).

## Limits
- Simulated scenes from one flat piece set; no real screen footage, lens distortion or moire.
- Detection runs batched per game (the detector is stateless per image), not as a live stream.
- Calibration needs a clean start frame: a hand or glare on it rejects the start (by design).
- Policy set on smoke/dev and single-position dev scenes only; heldout was not used for tuning.

## Measured 2026-11-15 (simulated images only; policy sha256 60c9b068...a218, frozen before heldout)
- dev games (12): 0 wrong accepted in both modes; 5 starts rejected (3 black-queen colour vote < 0.75,
  2 banding); re-review mode 177/251 correct, 29.5 re-reviews/100 frames (easy 2.0, medium 64.8, hard 75.8).
- single-position dev scenes (209, cross-scene calibration): 0 wrong squares on undisturbed scenes;
  46-49 wrong-confident squares (of 13.3k) under glare/banding/hand, identical with true corners.

## Round 2 (agreement guard; policy sha256 98b20985...0f61 = v2, AGREE 2, skip-unusable; frozen)
- dev, AGREE_FRAMES=1 vs round-1 report: 133 numbers compared, 0 differences. smoke2: 14/14 positions.
- dev2 re-review, AGREE 1 vs 2: 0 vs 0 wrong; 25.7 vs 40.1 re-reviews/100 positions; 0 guard-blocked.
