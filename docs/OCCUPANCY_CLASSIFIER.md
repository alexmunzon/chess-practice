# Three-way occupancy classifier (experiment, 2026-11-15)

Prototype of the research recommendation: label each square only EMPTY / WHITE / BLACK (or UNKNOWN),
using colour references learned from one human-confirmed starting frame, never piece templates.
Code: `scripts/recognition/occupancy_classifier.py`. Tests: `python3 -B tests/occupancy_classifier.py`.
Outputs: `/Users/alexmunzon/chess-builds/occupancy-classifier-2026-11-15/`. Not wired into the app.

## Method
- Geometry: the simulation's marker finder and rectifier (`scripts/simulation/recognize.py`), nothing else.
- `calibrate(panel, occupancy)`: from ONE frame learns empty-light, empty-dark, white-on-light,
  white-on-dark, black-on-light, black-on-dark. Rejects the frame (CalibrationError) if any square
  disagrees with the stated occupancy, if a class has < 2 squares, or if "white" is not lighter than "black".
- `classify(panel, calibration)`: per frame, a linear lighting correction maps this frame's light/dark
  square borders onto the calibrated ones. Per square: border ring must look like empty board
  (else occluded); foreground fraction decides empty vs piece; colour is a vote of the pixels deepest
  inside the piece silhouette (above the base), nearest white vs black reference. Any failed gate = unknown.
- Confidence = minimum of four 0-1 component scores, each scaled so its gate sits at 0.5; abstain below 0.5.

## Fixed thresholds (recorded in every output JSON as `policy`)
FG_DISTANCE 40 RGB; EMPTY_MAX_FG 0.03; PIECE_MIN_FG 0.08; BORDER_MAX_FRAC 0.20; COLOR_VOTE_MIN 0.75;
COLOR_MAX_DIST 70; SATURATED 250 / 5 %; GAIN_RANGE 0.5-2.0; core depth >= 2 px, band 3, rows < 46;
ABSTAIN_BELOW 0.5. Tuned on dev frames only, then frozen before held-out, challenge or sweep scoring.
Dev-only changes before freezing: colour moved from a median to a pixel vote, outlines and the piece
base excluded (drawn pieces have opposite-colour outlines and outline-heavy bases).
After freezing, only extra sweep stress levels were added; no threshold changed.

## Corpus results (calibration frame itself not scored)
Calibration: dev-opening, heldout-opening and fixture-repetition use their own first frame.
Sessions not starting from the standard start, and challenge sessions whose start was rejected,
borrow dev-opening's calibration (frame 000000).

| Split / category | Frames | Squares | Correct | Wrong (confident) | Abstained | All 64 correct |
|---|---|---|---|---|---|---|
| dev clean | 38 | 2432 | 2432 | 0 | 0 | 38 |
| dev perspective (side ratio >= 1.04) | 14 | 896 | 896 | 0 | 0 | 14 |
| held-out (all "lighting": palette shift, brightness 0.89-1.07) | 13 | 832 | 832 | 0 | 0 | 13 |
| challenge (occlusion, missing marker, unfamiliar style, glare, severe blur) | 10 | 640 | 328 | 0 | 312 | 0 |

Challenge detail: occlusion 15 squares unknown per frame; glare 10; unfamiliar slender pieces 3
unknown, 61 correct; missing marker and severe blur fail geometry, so all 64 unknown (classifier not reached).
Own-start calibration was correctly rejected for all 5 challenge sessions.

## Robustness sweep (30 dev frames per level, 1920 squares; perturbed copies saved under sweep-examples/)
SWEEP_TABLE

## Honest reading
- These are rendered images of one known 2D piece style on a flat screen board with coloured
  markers. Held-out shares the artwork and lighting model. Zero wrong-confident here says the logic
  is safe on easy pixels, not that it works on camera frames of real 3D pieces.
- What failed or is weak: gamma 0.6/1.6 and noise sigma 24 break the MARKER finder (geometry), not
  the classifier; brightness +15/+30 % clips white pieces, which abstain (safe but useless); the
  unfamiliar style already costs 3 squares; colour reading needed artwork-specific dev fixes
  (outline and base exclusion), a sign it is brittle to piece design.
- Abstentions are honest but frequent under glare/occlusion; nothing here fills them in.

## Top 3 changes before real glasses frames
1. Real geometry: replace marker rectification with board-corner detection plus a per-square
   height-aware crop (3D pieces lean into neighbouring squares under perspective, which the border
   gate would read as occlusion).
2. Learn colour from real pieces: replace the "deep core above the base" rule with references
   sampled from the confirmed start frame's whole visible piece body, plus shadow-tolerant colour
   space (chromaticity + lightness) instead of raw RGB distance.
3. Use change detection between frames: compare each square to its own last confirmed appearance
   and only re-classify squares that changed, so one move touches 2-4 squares and everything else
   inherits confirmed state.
