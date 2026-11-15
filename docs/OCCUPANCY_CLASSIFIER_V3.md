# Square reader v3 (experiment, 2026-11-15, simulated images only)
Same API as v2 (`calibrate`, `classify`, `occupancy_from_fen`, `CalibrationError`, `policy()`, `SQUARES`);
v2 stays frozen. Code `scripts/recognition/occupancy_classifier_v3.py` (sha256 `16c14a0a...685c3`,
frozen 2026-11-16); harness `scripts/recognition/evaluate_classifier_v3.py`; tests
`python3 -B tests/occupancy_classifier_v3.py` (v2's 11 cases plus 7 new); outputs
`/Users/alexmunzon/chess-builds/pipeline-2026-11-15/classifier-v3/`. Not wired into the pipeline.

## What changed versus v2 and why
- **v2's failure.** Every v2 wrong square on development data (6 dev game, 49 single-scene, 62 dev2) was a
  bare square under a refresh stripe or glare: one global lighting correction cannot follow a stripe,
  so the bright band counts as "foreground" and its colour votes white or black. Crops: `v2-failures/`.
- **Local lighting.** After the global correction, each square measures its own left/right bare strips
  row by row and fits them with a physical model: banding = brightness factor (|k| <= 0.20), glare = added
  grey light (never negative). Only the fitted lighting is removed, so a hand or occluder stays visible.
- **Two cues must agree.** Colour difference from the corrected board AND vertical edges (piece
  outlines). Stripes and glare are smooth and near-horizontal, so they cannot fake vertical edges.
  Disagreement is unknown, never piece or empty.
- **Gates.** Local shift, row-to-row step, left/right difference, unexplained colour; a square next to
  a sharp lighting edge (occluder edge) is unknown, because a fully covered square can look like lit board.
- **Colour.** v2's depth-weighted core vote, with the silhouette closed over 1-2 px outline gaps, >= 40
  core pixels (outline-only silhouettes were read as the wrong colour), references from the bright/dark
  half of the start pieces' core pixels.
- **Start check.** Same measurement as classify; a banded start passes only if every square passes the
  normal gates. The stated colour must win each square by 0.60 and average 0.85 per colour (v2 needed
  0.75 everywhere; the outline-heavy black queen sat at 0.65-0.74).
- **Fewer needless unknowns.** v2's undisturbed unknowns were mostly whole frames dropped by the gain
  range (0.5-2.0, hard frames have contrast x brightness down to 0.36) and clipped white pieces. Gain
  range is now 0.33-3.0; clipped pixels are allowed when the ring is unclipped and local lighting is calm.

## Results (wrong-confident / unknown / correct squares; "common" = frames both versions could score)
| data | corners | v2 all | v3 all | v2 common | v3 common |
|---|---|---|---|---|---|
| dev games | true | 6 / 1046 / 15012 | 0 / 1618 / 25326 | 6 / 1046 / 15012 | 0 / 576 / 15488 |
| dev games | detected | 6 / 982 / 15012 | 0 / 1543 / 25273 | 6 / 982 / 15012 | 0 / 511 / 15489 |
| dev2 games | true | 62 / 5173 / 47885 | 0 / 3955 / 55629 | 62 / 5173 / 47885 | 0 / 3099 / 50021 |
| dev2 games | detected | 63 / 5175 / 47882 | 0 / 3955 / 55629 | 63 / 5175 / 47882 | 0 / 3097 / 50023 |
| single dev scenes (209) | true | 49 / 2909 / 10418 | 0 / 2214 / 11162 | same set | |
| single dev scenes | detected | 46 / 2843 / 10423 | 0 / 2137 / 11175 | same set | |
smoke and smoke2: 0 wrong, 0 unknown for both. Starts accepted (true and detected corners alike):
dev 7/12 -> 12/12, dev2 10/12 -> 11/12 (dev2-g02: very soft start, pieces fail the edge cue), smoke and
smoke2 all; every accepted start has the correct orientation. Single start scenes: 5/14 both (cross-palette).
Undisturbed unknown % (common frames, v2 -> v3): dev medium 7.1 -> 0.0, hard 6.9 -> 0.0; dev2 medium
3.5 -> 0.6, hard 17.1 -> 8.6; easy 0 -> 0; single scenes all undisturbed 6.4 -> 0.7.
Original marker corpus (v2's own logic): dev 52 frames 3328/3328 correct both; challenge 0 wrong both,
v3 abstains more (370 vs 312 of 640). Early v3 drafts made 4 wrong there (a white box covering whole
squares was "explained" as lighting), which is why the physical model and neighbour rule exist.
Negative controls (tests): one square off, swapped colours, rotated 90/180, flipped, hand or glare over
pieces, incomplete claim: all rejected. A left-right mirrored start is occupancy-identical: undetectable.

## Robustness sweep (36 undisturbed dev frames, 2304 squares per level; wrong v2 / v3)
v3 wrong = 0 at every level. v2 wrong appears only with the new disturbances: banding amp 0.1-0.3
(5-20 per level) and bright spots (3-21 per level). Abstention v2 -> v3: none 2.9 -> 0; brightness x0.5
52.8 -> 2.8, x1.3 27 -> 7.8; blur r2 4.5 -> 19.2, r3 10 -> 35 (v3 worse: edge cue), r4-5 100 both;
noise 40 8.9 -> 14.1; misreg 4+4 85 -> 37, 8 px 100 both; glare r40 6.9 -> 19, r90 15 -> 31; banding amp
0.2 period 40-100 untilted ~66 -> 2-4, tilted 10 deg and period 16 up to 100 (frame gates); spots 0-28.
Full table: `sweep.json`, `sweep1.log`.

## Where each threshold came from (all dev data only; `policy()` lists all 38 constants)
Kept from v2 (tuned on the marker corpus dev split): FG_DISTANCE, EMPTY/PIECE_MIN_FG, BORDER_MAX_FRAC,
SATURATED_*, COLOUR_MAX_ROW, CORE_*, COLOR_VOTE_MIN, COLOR_MAX_DIST, FRAME_SHARPNESS_MIN, ABSTAIN_BELOW.
Set on dev + smoke game frames and single dev scenes (distributions of undisturbed vs disturbed squares):
EDGE_LEVEL, EMPTY_MAX_EDGE, PIECE_MIN_EDGE, LOCAL_* (about 2-4x the undisturbed maximum), MIN_FILL_PIXELS,
SATURATED_OK_*, GAIN_RANGE; LOCAL_MAX_MULT / DARK_HAZE / NEIGHBOUR_RULE also from the corpus challenge
split; CAL_VOTE_* from dev game starts. dev2 arrived after tuning and was scored once, unchanged.

## Limits
Simulated pictures, one flat 2D piece style with opposite-colour outlines, one renderer; the edge cue
relies on drawn outlines. Blur r2-3 costs more unknowns than v2. Held-out data never read.
