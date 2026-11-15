# Offline board calibration baseline

This is a separate prerecorded-image lab, not connected to capture, game guidance, or the browser UI. It never recognizes pieces or produces a FEN. Human-approved board corners are only a calibration, not an approved chess position.

## Concrete reuse

`BoardCandidates.swift` adapts ImageIO file loading, `VNDetectRectanglesRequest`, CoreImage `CIPerspectiveCorrection`, and JSON reporting from `../blackjack-practice/native/RecognitionLab/CardRecognizer.swift` (preserved experimental baseline commit `c60a2d1`). The original code is unchanged. Card OCR, card ranks, and card confidence logic are deliberately not reused as chess recognition.

Apple Vision proposes up to 24 rectangles and writes perspective-corrected candidate PNGs. Python applies a checker-alternation heuristic to normalized crops, returns tentative candidates, and builds a projective 8×8 source-pixel square map. This heuristic does not distinguish a chessboard from a similar checker pattern and is not a calibrated confidence score.

## Run on macOS

Requires installed Swift/Apple Vision/CoreImage, Python 3, Pillow and NumPy. No installs, remote vision API, or models are needed.

From the chess-practice root:

```sh
swiftc native/BoardVision/BoardCandidates.swift -o /tmp/chess-board-candidates
python3 scripts/vision/calibrate.py /path/to/photo.jpg \
  --detector /tmp/chess-board-candidates --output /tmp/chess-calibration
python3 tests/vision_calibration.py /tmp/chess-board-candidates /tmp/chess-vision-benchmark
```

JSON is printed to stdout and saved as `calibration.json`. Images and outputs go only to the requested output directory. On a successful proposal, inspect `grid-review.png` against the input and `board-normalized.png`. A selected candidate is always `needs-human-confirmation` by default. If the crop misses board boundaries, use manual calibration instead. The detector may select an outer border rather than actual playing-square corners.

Manual four-corner fallback, explicitly separate from automatic detection:

```sh
python3 scripts/vision/calibrate.py /path/to/photo.jpg \
  --corners '[[150,150],[650,150],[650,650],[150,650]]' \
  --orientation white-bottom --output /tmp/chess-manual
```

Coordinates refer to EXIF-oriented source pixels with top-left origin, in convex clockwise TL, TR, BR, BL order. Four corners must mark the playing surface, not the decorative frame. White-bottom maps top-left to a8; black-bottom maps top-left to h1. For a sideways board, rotate the source to put a player's home rank at the bottom before calibrating; arbitrary chess orientation is not inferred. A missing orientation leaves square names null. Manual corners are rejected when degenerate, self-crossing, non-finite, or outside the image.

After personally reviewing the corners/grid and selecting orientation, rerun the same command with `--confirm-calibration`. This records only the operator's explicit confirmation. The code cannot verify that review actually occurred. It does not confirm pieces, legal position, side to move, castling, en passant or move clocks. Those fields remain null, as does `fen`, even for a confirmed calibration. These must be supplied and verified separately before engine advice.

## Measured baseline (2026-11-10)

Generated 800×800 scenes with a 512×512 empty checkerboard and known ground-truth quadrilaterals. Measured corner error is mean Euclidean distance over the four source corners, not piece-recognition accuracy.

| Scene | Board proposed | Mean corner error |
| --- | --- | --- |
| Frontal | yes | 11.18 px |
| Perspective | yes | 11.27 px |
| Rotation | yes | 9.74 px |
| Gaussian blur, sigma 4 | no (abstained) | n/a |
| Local white glare | yes | 11.18 px |
| Covered board negative | no (rejected rectangle) | n/a |
| Plain rectangle negative | no (rejected rectangle) | n/a |

Four of five positive scenes proposed candidates; both negative controls abstained. This tiny fixture set is not a statistically valid accuracy estimate. ~10–11 px boundary error is material and warrants manual review. Tests assert fewer than 20 px error when a synthetic candidate is selected, at least three positive proposals, both negative abstentions, null FEN, 64-square mapping, manual orientation and invalid-corner rejection. Vision output may differ across OS versions.

One real physical board image was also evaluated: **Chess board opening staunton**, Staxringold, own work, uploaded 11 July 2006, CC BY-SA 3.0 (metadata verified via Wikimedia API on 2026-11-10).

- Source: https://commons.wikimedia.org/wiki/File:Chess_board_opening_staunton.jpg
- License: https://creativecommons.org/licenses/by-sa/3.0/
- Original: https://upload.wikimedia.org/wikipedia/commons/c/c3/Chess_board_opening_staunton.jpg
- Evaluated dimensions: 2611×1699. Result: **abstained, no rectangle candidates**. No ground-truth corners were annotated, so no real-photo corner accuracy is claimed.

The real photo and all derivatives are in temporary local storage only, not in delivered source. One failed real-photo case and blur failure establish that automatic physical-board recognition is not ready. Manual calibration is the usable fallback; actual piece recognition remains unimplemented.

## Grid-line fallback, version 2

The baseline above is retained verbatim as historical evidence. The current Python CLI adds a bounded NumPy grid-line fallback when no Vision rectangle passes the checker filter. It downsamples to at most 640 pixels, performs gradient-weighted Hough voting for two near-axis line families, refines lines, fits a vertical line pencil and projective horizontal spacing, and enumerates possible missing outside lines. No manual corners, filenames, starting positions or known piece locations are used as detector inputs.

The checker filter additionally samples four small patches near each tile's corners, where pieces occlude less of the surface than at the center. It accepts tile-corner alternation correlation ≥0.85 with contrast ≥25, or the original center correlation ≥0.75 with contrast ≥25. These scores are heuristics, never probabilities. A checkerboard without chess pieces can pass. Grid extrapolation assumes visible consecutive lines and a near-axis board; irregular borders, stronger perspective, heavy occlusion or rotated physical views may still fail.

Algorithm parameters were frozen before the integrator's held-out image evaluation: 640px thumbnail, Gaussian sigma1, absolute gradient >max(8,p90), slope range [-0.5,0.5] in 0.01 increments, retained votes ≥45% of peak with 9px separation; 3–9 horizontal and 5–9 vertical lines; vertical fit residual ≤3px and spacing ratio ≤1.5; horizontal projective residual ≤2px and spacing ratio ≤1.7. No new dependencies were installed.

On the development-only Staxringold photo, this produces an automatic proposal with **6.99px mean and 14.05px maximum corner error**, relative to manually labelled corners with approximately 10px annotation uncertainty. The annotations were recorded from original pixels before developing the fallback, and never passed to it. See `development-annotation.json` and `benchmark-grid-v2.json`. This is a development result, not evidence of generalization. The five synthetic positives now all produce candidates, including sigma4 blur at 1.37px mean error; both negatives still abstain. The four existing positive results are unchanged. The first physical-photo failure is preserved in `benchmark-2026-11-10.json`.

The report is now schema version2. `sourceSha256` hashes the exact original file; `orientedRgbSha256` hashes decoded, EXIF-oriented RGB bytes, and `imageSize` gives their dimensions. Downstream consumers must verify source identity and oriented dimensions before applying polygons. `selectedGeometryMethod` distinguishes manual, Apple Vision rectangle, and NumPy grid-line routes. Calibration confirmation still says nothing about piece accuracy or game state.

To evaluate without leaking ground truth into predictions:

```sh
python3 tests/vision_real.py --image /tmp/chess-real-staunton.jpg \
  --annotation native/BoardVision/development-annotation.json \
  --detector /tmp/chess-board-candidates --output /tmp/chess-real-evaluation
```

The annotation contract is documented by `development-annotation.json`: exact input hash, oriented dimensions, split, independently labelled TL/TR/BR/BL corners and uncertainty. `tests/vision_real.py` calls automatic calibration without those labels, then measures errors. It preserves abstentions instead of substituting manual predictions. It records the calibration source-code SHA256 in each evaluation. Do not tune on held-out evaluation results and continue calling those images held out.
