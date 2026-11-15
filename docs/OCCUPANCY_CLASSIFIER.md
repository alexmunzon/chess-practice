# Three-way occupancy classifier (experiment, 2026-11-15)
Labels each square EMPTY / WHITE / BLACK / UNKNOWN from colour references learned on ONE human-confirmed
start frame; never uses piece templates or piece types. Not wired into the app.
Code `scripts/recognition/occupancy_classifier.py` (`evaluate`, `sweep` modes); tests
`python3 -B tests/occupancy_classifier.py`; outputs `/Users/alexmunzon/chess-builds/occupancy-classifier-2026-11-15/`.

## Method
- Geometry only from the simulation marker finder/rectifier (`scripts/simulation/recognize.py`).
- `calibrate(panel, occupancy)` learns empty-light/dark, white-on-light/dark, black-on-light/dark. It raises
  CalibrationError if any square disagrees with the stated occupancy, a class has < 2 squares, or white is not lighter.
- `classify(panel, calibration)`: linear per-frame lighting correction (frame's light/dark borders mapped
  onto calibration); per square, border ring must look like bare board (else occluded), foreground fraction
  decides empty vs piece, colour = depth-weighted vote of pixels deep inside the piece silhouette (above its base).
- Confidence = min of component scores, each scaled so its gate is 0.5; abstain below 0.5.

## Fixed thresholds (written into every output JSON as `policy`)
FG_DISTANCE 40 RGB; EMPTY_MAX_FG 0.03; PIECE_MIN_FG 0.08; BORDER_MAX_FRAC 0.20; COLOR_VOTE_MIN 0.75;
COLOR_MAX_DIST 70; saturated >= 250 on > 5 %; GAIN 0.5-2.0; core depth >= 2 px, band 3, tile rows < 46;
ABSTAIN_BELOW 0.5. Tuned on dev frames only, frozen before held-out/challenge/sweep scoring (v1).
Dev-stage fixes: median colour -> pixel vote; outlines and bases excluded (drawn pieces have opposite-colour
outlines). Post-freeze (v2): FRAME_SHARPNESS_MIN 0.4 added after the sweep failure below; held-out re-run.

## Corpus results (calibration frame not scored; identical under v1 and v2)
Own first frame calibrates dev-opening, heldout-opening, fixture-repetition; other sessions (non-standard
starts, and challenge sessions whose own start was correctly rejected) borrow dev-opening frame 000000.

| Split / category | Frames | Squares | Correct | Wrong-confident | Abstained | All 64 correct |
|---|---|---|---|---|---|---|
| dev clean | 38 | 2432 | 2432 | 0 | 0 | 38 |
| dev perspective (side ratio >= 1.04) | 14 | 896 | 896 | 0 | 0 | 14 |
| held-out (all lighting: palette shift, brightness 0.89-1.07) | 13 | 832 | 832 | 0 | 0 | 13 |
| challenge | 10 | 640 | 328 | 0 | 312 | 0 |

Challenge: occlusion 15 unknown/frame, glare 10, unfamiliar style 3 (61 correct); missing marker and severe blur fail geometry (all 64 unknown).

## Robustness sweep (30 dev frames x 64 = 1920 squares/level; "[panel]" = clean geometry, perturbed classifier input)

| Perturbation | Geometry fails | Wrong v1 | Wrong v2 | Abstain v2 |
|---|---|---|---|---|
| brightness x0.7 / x0.85 / x1.15 / x1.3 | 0 | 0 | 0 | 0 / 0 / 25 / 47 % (white pieces clip) |
| gamma 0.6, 1.6 (image) / [panel] | 30 each / 0 | 0 | 0 | 100 % / 0 % |
| blur r1 / r2 / r3 | 0 | 0 | 0 | 0 / 1.6 / 10.6 % |
| JPEG q70 / q50 / q30 | 0 | 0 | 0 | 0 % |
| noise sigma 8 / 16 / 24 (24 [panel]) | 0 / 0 / 30 (0) | 0 | 0 | 0 / 0 / 100 % (0 %) |
| glare blob r40 / r90 | 0 | 0 | 0 | 4.0 / 12.6 % |
| misregistration 1, 2, 2+2 px | 0 | 0 | 0 | 0 % |
| **stress: blur r5** | 0 | **452 (23.5 %)** | 0 | 100 % |
| stress: misreg 4+4 / 8 / 16 px; brightness x0.5; noise 40 [panel] | 0 | 0 | 0 | 91 / 100 / 100; 86.7; 0.1 % |

v1 failure: at blur r5 bare light squares were called "white" with confidence: blur pulls light/dark border
colours together and the lighting correction over-stretches contrast. v2 adds a frame-level sharpness gate
(boundary contrast vs calibration frame; r3 passes, r5 abstains whole frame). Gate value picked on dev sweep
frames only. v1 code/outputs: `v1-frozen/` in the output folder; perturbed examples in `sweep-examples/`.

## Honest reading
- Rendered images of one known 2D piece style on a flat marked board; held-out shares artwork and lighting
  model. Zero wrong-confident means the logic is safe on easy pixels, not that it works on camera frames.
- Weak spots: gamma and strong noise break the MARKER finder, not the classifier; +15-30 % brightness clips
  white pieces into abstention; unfamiliar artwork already costs squares; colour reading needed
  artwork-specific dev fixes (outlines, bases). The frozen policy made confident errors under heavy blur,
  and one global lighting correction remains a single point of failure.

## Top 3 changes before real glasses frames
1. Real geometry: board-corner detection instead of markers, plus height-aware square crops (3D pieces lean
   into neighbouring squares, which the border gate would read as occlusion).
2. Colour model for real pieces: references from the whole visible piece body in the confirmed start frame,
   in a shadow-tolerant space (chromaticity + lightness), with local not global lighting correction.
3. Change detection: compare each square to its own last confirmed appearance and re-classify only squares
   that changed, so a move touches 2-4 squares and the rest inherits confirmed state.
