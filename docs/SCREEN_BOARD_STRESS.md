# Corner finder under lens distortion and motion blur (experiment, 2026-11-16, simulated images only)

Question: the screen pipeline accepted the start picture in only 1 of 3 lens-distortion games and 2 of 3
motion-blur games on stressdev. Is the corner finder (`native/ScreenBoardVision`) the stage that rejects them?

## Answer
No. The corner finder accepted every lens and blur picture; the square reader's start calibration
refused them. The causes differ:
- Motion blur 12 px (`motion-blur-g2`): the finder's corners are 0.01% of the board side off. The square
  reader refuses even with the TRUE corners (8 squares "stated-occupied-but-empty": blurred pieces read
  as empty). Cause: square reader. Nothing to fix in the finder.
- Lens distortion, edge bow 1% and 2% (`lens-distortion-g1`, `-g2`): the finder's corners are 2.07% and
  3.86% of the side off, because a straight-line (homography) fit cannot follow curved board edges. The
  square reader refuses with the finder's corners (7 / 17 squares disagree) and even more with the TRUE
  corners (24 / 52), because the pipeline rectifies with a homography from 4 corners, which cannot be
  exact on a curved board. After undistorting the picture with the generator's known lens parameter, the
  reader accepts all 3 lens starts. Cause: straight-line rectification of a distorted picture. More
  accurate corners would not help (true corners are worse for the reader than the finder's).

Evidence: `/Users/alexmunzon/chess-builds/corner-finder-2026-11-16/logs/start-stage-base.txt`
(script `start_stage_check.py` in the same folder, using the pipeline's own `rectify` and v3 `calibrate`):

| start picture | finder | corner error | reader, finder corners | reader, true corners | reader, undistorted |
|---|---|---|---|---|---|
| lens g0 (bow 0.5%) | ok | 0.90% | accepts | accepts | accepts |
| lens g1 (bow 1%) | ok | 2.07% | 7 squares disagree | 24 disagree | accepts |
| lens g2 (bow 2%) | ok | 3.86% | 17 disagree | 52 disagree | accepts |
| blur g0 (3 px) | ok | 0.00% | accepts | accepts | n/a |
| blur g1 (6 px) | ok | 0.01% | accepts | accepts | n/a |
| blur g2 (12 px) | ok | 0.01% | 8 disagree | 8 disagree | n/a |

## The safety gap found, and the change
The finder never noticed curvature: on stronger distortion than stressdev has, it accepted wrong corners.
A test set made from dev2 pictures (2 per game, barrel k1 -0.15 to -0.5, same model as the scene
generator; `make_strong_lens.py`) gave 41 of 96 accepted with corners 5.0% to 22.6% of the side off.

Change, round 1 (`ScreenBoardDetector.swift`, `main.swift`; replaced in round 2 below): after the robust grid fit, the same refined grid points
are fitted with a homography plus one radial lens term about the image centre (k1 searched in
[-0.6, 0.6]). If the outer corners of the two fits differ by more than 2.5% of the board side, the
finder abstains with `board-edges-curved`. The 2.5% limit is half the 5% wrong-corner line, chosen
before looking at results. The finder uses only the picture. Reported corners are unchanged; output
diagnostics gain `lensK1` and `curveShiftPctSide`. The estimate tracks the real error: on lens g1 it
finds k1 -0.089 (generator: -0.0893) and predicts 2.03% where the real error is 2.07%.

## Before / after (finder alone; correct = found and worst corner within 5% of the mean board side,
as in `evaluate.py`; wrong = found and more than 5% off)

| split / variant | pictures | before correct / wrong / rejected | after correct / wrong / rejected |
|---|---|---|---|
| smoke | 16 | 16 / 0 / 0 | 16 / 0 / 0 |
| dev | 433 | 431 / 0 / 2 | 431 / 0 / 2 |
| smoke2 | 48 | 48 / 0 / 0 | 48 / 0 / 0 |
| dev2 | 1047 | 1047 / 0 / 0 | 1047 / 0 / 0 |
| stressdev, 11 variants other than lens | 1347 | 1347 / 0 / 0 | 1347 / 0 / 0 |
| stressdev lens-distortion | 126 | 126 / 0 / 0 | 87 / 0 / 39 (all of g2, bow 2%) |
| strong lens k1 -0.15 (bow 0.1-2.0%) | 24 | 24 / 0 / 0 | 17 / 0 / 7 |
| strong lens k1 -0.25 (bow 0.2-3.6%) | 24 | 20 / 4 / 0 | 4 / 0 / 20 |
| strong lens k1 -0.35 (bow 0.3-5.6%) | 24 | 6 / 18 / 0 | 4 / 0 / 20 |
| strong lens k1 -0.5 (bow 0.5-10.6%) | 24 | 4 / 19 / 1 | 3 / 0 / 21 |

No picture on smoke, dev, smoke2, dev2 changed outcome; the 2976 pictures correct in both runs have
identical corner errors (mean 0.069%, max 2.37% of side). The largest curve shift on any accepted
non-lens picture is 0.33% of side (2889 pictures), far below 2.5%. Lens g1 pictures sit at 2.0-2.35%,
close to the limit: they are still accepted by the finder (and still refused by the square reader).
Lens g2 start is now refused by the finder instead of the square reader; the pipeline outcome is the same.

Detection time (same 121 pictures, every 25th of the run, both binaries alternating, 3 rounds, Apple
M1 shared with other jobs, load 10-17, `detectMs` excluding decode): before mean 103.7 ms, p95 158.4 ms;
after mean 88.7 ms, p95 107.1 ms (median of 3 rounds per picture). Round means: before 129.4 / 105.1 /
105.5, after 93.8 / 92.1 / 93.3. The lens fit costs no measurable time; the difference is machine load.

## What the pipeline would need (outside this module; not done)
1. Lens undistortion before the finder and the rectifier. Best: a one-time calibration of the glasses
   camera (centre, k1, k2), applied to every picture; the finder's per-picture `lensK1` estimate agrees
   with the generator here but is one picture's fit and should only cross-check a calibration.
   Shown above: with undistortion the square reader accepts all 3 lens starts (1 of 3 today).
2. The pipeline treats `board-edges-curved` like any other `found: false` (it already does: no code change
   needed to stay safe).
3. Motion blur 12 px: the square reader (occupancy classifier v3) reads blurred pieces as empty; a fix
   belongs there, or in rejecting blurred pictures before reading.

## Round 2 (after independent review): lens centre fitted, non-finite values reject
The review found two faults in round 1 (`bin-new`):
1. With the lens centre 300-350 px off the picture centre and k1 -0.3, the fixed-centre fit saw only
   27-43% of the real corner error; 4 of 72 review pictures were accepted 5.24-7.81% off.
2. A NaN shift would have passed both comparisons.

Change (`bin-new2`): the lens fit now also finds the lens centre (anywhere in the picture: 5x5 grid of
start centres, 1-D k1 search each, then a pattern search over centre and k1). The undistortion step
must converge, and any non-finite value means `lens-fit-failed` (reject). Decision code is in
`curveVerdict` / `curveShift` and is checked without pictures by `Checks/CurveCheck.swift`. The limit
stays at 2.5%. A second free term (k2) was tried and dropped: 3x slower and still missed cases, because
the grid inside the board cannot tell such profiles apart.

Results (correct / wrong / rejected; wrong = accepted more than 5% of side off):

| set | n | bin-base | bin-new | bin-new2 |
|---|---|---|---|---|
| review offcentre (centre 300-400 px off) | 72 | 37 / 32 / 3 | 28 / 4 / 40 | 15 / 0 / 57 |
| review between (k1 -0.1 to -0.42) | 96 | 59 / 37 / 0 | 38 / 0 / 58 | 38 / 0 / 58 |
| review k2 (centred) | 96 | 76 / 20 / 0 | 61 / 0 / 35 | 58 / 0 / 38 |
| review occluded | 72 | 39 / 33 / 0 | 12 / 0 / 60 | 12 / 0 / 60 |
| review pincushion | 80 | 69 / 11 / 0 | 42 / 0 / 38 | 42 / 0 / 38 |
| review smallboard | 96 | 66 / 16 / 14 | 33 / 0 / 63 | 38 / 0 / 58 |
| review tiltblur | 72 | 49 / 23 / 0 | 27 / 0 / 45 | 27 / 0 / 45 |
| review ordinary (no lens) | 69 | 68 / 0 / 1 | 68 / 0 / 1 | 68 / 0 / 1 |
| offset sweep, centre 0-350 px in 50 px steps, 8 directions, k1 -0.4 to +0.3 | 220 | 161 / 56 / 3 | 113 / 0 / 107 | 107 / 0 / 113 |
| own strong-lens set | 96 | 54 / 41 / 1 | 28 / 0 / 68 | 27 / 0 / 69 |
| smoke, dev, smoke2, dev2, stressdev | 3017 | 3015 / 0 / 2 | 2976 / 0 / 41 | 2976 / 0 / 41 |

On the splits no picture changed outcome from `bin-new` to `bin-new2`, and corners are identical
wherever both accept. Largest shift on an accepted non-lens picture: 0.72% of side (was 0.33%).
On the offset sweep, every offset step from 0 to 350 px has 0 wrong with `bin-new2`; 8 pictures that
`bin-new` accepted (real error 2.6-4.2%) are now rejected, with the measured shift matching the real
error. On the review offcentre set the measured shift is now 0.55-1.0x the real error (median 0.95).

Check without pictures (`curve-check`, 1412 synthetic grids, lens centre 0-350 px off in 8 directions,
3 board positions): for one-term lenses (k1 from -0.45 to +0.45), 0 of 279 grids with corners more
than 5% off pass, and the shift is at least 0.80x the real error. For profiles with a k2 term (k2
only, or k1 and k2 of opposite signs) combined with a centre 150 px or more off, 24 of 188 such grids
pass with real errors of 5.1-6.6% (shift as low as 0.08x the error). The checks for non-finite
values: 8 of 8 pass.

Detection time (same 121 pictures, three binaries alternating, 3 rounds, load 6-8, median of 3 per
picture): `bin-base` mean 74.5 ms (p95 79.5), `bin-new` 74.5 ms (p95 78.9), `bin-new2` 91.8 ms (p95 100.2).
The free-centre fit costs about 17 ms per picture.

## Limits
- Simulated pictures only. The check knows one radial term with a free centre, so it is an
  improvement, NOT a guard against lens distortion. An independent re-review (2026-11-16,
  `/Users/alexmunzon/chess-builds/review-corner-finder-round2-2026-11-16/`) made 422 pictures with
  a second radial term (k2): the round-2 binary accepted 24 of them with corners 5.0% to 16.6% off.
  A lens centre 150 px off the picture centre is enough, and the common real-lens shape (k1
  negative, k2 positive) is among them. One-term lenses were safe (0 wrong of 91 accepted). Letting
  the centre move freely also made 2 pictures worse than round 1 (accepted 5.31% and 10.95% off,
  refused before). A lower limit does not close the gap: at 1.5%, 11 of the 24 still pass and 84 of
  211 correct boards are lost; at 0.5%, 5 still pass. If the centre search reaches its 400-iteration
  cap the picture is judged on the best fit so far, not rejected. Tangential distortion and rolling
  shutter are not modelled. On the same 1,006 distorted pictures the original finder accepted 277
  wrong boards, round 1 accepted 47 and round 2 accepted 24. The sound fix is undistortion with the
  glasses camera's calibrated lens values before the finder (outside this module); until then,
  treat pictures from an uncalibrated wide lens as unsupported.
- The strong-lens, review and offset-sweep sets are dev2-derived pictures made for these tests, not
  glasses footage.
- The check rejects; it never corrects. With a wide lens and no undistortion, boards near the frame
  edge will be refused.
- Held-out splits were not read or scored.

Files: `/Users/alexmunzon/chess-builds/corner-finder-2026-11-16/` (binaries `bin-base`, `bin-new`, logs,
`score_corners.py`, `start_stage_check.py`, `make_strong_lens.py`, `strong-lens/`; round 2 in
`round2/`: `bin-new2`, `curve-check`, `make_offset_sweep.py`, `score_review_sets.py`, `logs/`).
