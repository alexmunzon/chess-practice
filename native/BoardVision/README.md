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
