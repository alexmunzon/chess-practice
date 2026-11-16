# Screen board corners (experiment, not app code)

Finds the four outer corners of an 8x8 chess board shown on a screen, seen at an angle by a
head-worn camera, without the corpus corner markers. Corners are clockwise (y down) from the one
nearest the image top-left; which side is white is out of scope (corners are up to 90° rotation).

## Method (`ScreenBoardDetector.swift`, Foundation + CoreGraphics + ImageIO only)

1. Gray, 2x downsample, blur σ 0.8; ChESS X-corner response (16-sample ring, radius 5), 7x7
   non-max suppression, ≤900 candidates, each with a ring phase that flips between neighbours.
2. Lattice growth: from strong seeds, two short non-collinear opposite-phase neighbours give a
   basis; the lattice grows by homography prediction (match within 0.28 square, phase must
   alternate). Bezel, page edges, window mullions and keyboard keys make no X-corners, so the
   outer rectangles can never be chosen. A sparse 8th row (≤3 board-edge T-junctions) is trimmed;
   a fuller one means "grid larger than 8x8" and the frame is rejected.
3. Placement: every 7x7 internal-corner block consistent with the lattice is scored by (a) cell
   agreement: share of the 64 cells whose brightness alternates against their neighbours
   (sampled near cell corners, where pieces are not), minus (b) ring ratio: how strongly the
   checker continues one square outside any side.
4. Full-resolution sub-pixel refinement (window 0.22 square), robust homography refit; outer
   corners are lattice positions (−1, −1) … (7, 7).
5. Abstain unless: ≥16 lattice points, span ≥4 both ways, checker contrast ≥8 gray levels,
   cell agreement ≥0.80, ring ratio ≤0.45, placement margin ≥0.35 when several blocks fit, and
   confidence = agreement × (1 − ring) × min(1, points/25) × margin factor ≥0.55.
6. Curved-edge check (added 2026-11-16, see `docs/SCREEN_BOARD_STRESS.md`): the refined grid points are
   also fitted with a homography plus one radial lens term whose centre is fitted too (anywhere in
   the picture); if the outer corners of that fit and of the straight fit differ by more than 2.5% of
   the board side, or any value is not finite, abstain (`board-edges-curved` / `lens-fit-failed`).
   Output diagnostics gain `lensK1`, `lensK2` (always 0), `lensCentre` and `curveShiftPctSide` (null
   when not finite); corners are unchanged. Checks without pictures: `Checks/CurveCheck.swift`
   (build: `swiftc -O -parse-as-library GrayImage.swift Homography.swift ScreenBoardDetector.swift
   Checks/CurveCheck.swift -o curve-check`).
Parameters were set on dev only; held-out was run once after freezing.

## Scenes and run (outputs in `/Users/alexmunzon/chess-builds/screen-board-2026-11-15/`)

`scripts/recognition/make_screen_scenes.py` unwarps the 8x8 playing area of 23 distinct corpus
positions; the markers lie outside that area and are cropped away. Dev uses 16 positions and seeds
0–209, held-out uses the other 7 and seeds 100000–100149. Each split also has 24 negatives: no
board, 10x10 draughts, 6x6 and 9x9 checkers. Build with `swiftc -O GrayImage.swift Homography.swift
ScreenBoardDetector.swift main.swift -o screen-board-detect`, then score with
`python3 evaluate.py --binary … --split dev|heldout|sanity --out report.json`.

## Results (Apple M1, worst-corner error as % of board side; false accept = found and >5% off)

| Split / difficulty | n | found | ≤1% | ≤2% | false acc. | mean err px | p95 err px | ms/frame |
|---|---|---|---|---|---|---|---|---|
| dev easy | 70 | 100% | 100% | 100% | 0 | 0.03 | 0.10 | 113 |
| dev medium | 70 | 100% | 100% | 100% | 0 | 0.11 | 0.30 | 127 |
| dev hard | 70 | 98.6% | 98.6% | 98.6% | 0 | 0.26 | 1.00 | 101 |
| held-out easy | 50 | 100% | 100% | 100% | 0 | 0.04 | 0.10 | 100 |
| held-out medium | 50 | 100% | 100% | 100% | 0 | 0.09 | 0.30 | 94 |
| held-out hard | 50 | 98.0% | 98.0% | 98.0% | 0 | 0.24 | 0.93 | 99 |
| negatives (dev + held-out) | 48 | 0% | n/a | n/a | 0 | n/a | n/a | ~100 |
| sanity: 5 corpus PNGs, markers masked | 5 | 100% | 100% | 100% | 0 | 0.01 | 0.02 | 23 |

Mean error 0.02% of side (p95 0.13–0.15%). ~100 ms detect per 1920x1080 frame (p95 <180 ms) plus
~50 ms PNG decode, one core.

## Failure gallery

Only 2 of 360 positives missed, both safe abstentions: `dev-0047` (hard, glare, 33° pitch; lattice
spanned 3 columns) and `heldout-0053` (hand + glare + banding; ring test fired). Move-list text
beside the board caused ring rejections in dev until ring cells were densely sampled. Negatives:
6x6 → ambiguous placement, 9x9/10x10 → grid larger than 8x8, empty screen → too few X-corners.

## Honest limits

- Simulated scenes, not glasses footage: flat screen, no rolling shutter or real moiré; lens
  distortion only as one simulated radial term (the finder rejects strong curvature, it does not undo it); refresh banding is a crude sine and the hand a crude blob.
- One flat piece set that leaves square corners clear; real chess sites (big pieces, highlights,
  arrows, square coordinates) are untested and the likeliest way this breaks.
- Untested: boards <15% of frame width, motion blur. Confidence is heuristic, not calibrated.
- iOS: library files typecheck for arm64-apple-ios17.2 (iPhoneOS 26.2 SDK); not built into the
  app, not run on a phone, phone speed unknown.
Next: real glasses screen footage; busy chess-site themes and lens distortion in the generator;
frame-to-frame corner tracking; then square classification on the rectified board.
