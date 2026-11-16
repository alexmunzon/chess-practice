# Simulated screen-game scenes (experiment, 2026-11-15)

SIMULATED head-camera frames of whole chess games shown on a screen, with an answer key, for scoring
the screen pipeline end to end (corners -> square occupancy -> legal-move inference). Not camera
evidence: one 2D piece artwork (`scripts/simulation/appearance.py`), synthetic room, synthetic noise.

## Files
- `scripts/recognition/make_screen_game_scenes.py`: generator; imports canvas/room/keyboard/hand/homography
  helpers from `make_screen_scenes.py` (unchanged); per-game screen layout, room and camera track.
- `scripts/recognition/make-game-lines.mjs`: legal lines with chess.js (`lines`) and a move checker (`verify`).
- `tests/screen_game_scenes.py`: checks both roots. Output never in the repo:
  `/Users/alexmunzon/chess-builds/pipeline-2026-11-15/scenes/` (round one, frozen) and `.../scenes-v2/`.

## Run
```sh
G=scripts/recognition/make_screen_game_scenes.py; B=/Users/alexmunzon/chess-builds/pipeline-2026-11-15
python3 -B $G --out $B/scenes                       # round one: smoke, dev, heldout (default flags)
nice -n 10 python3 -B $G --out $B/scenes-v2 --suffix 2 --repeats-per-position 2 --workers 2
python3 -B tests/screen_game_scenes.py [--skip-determinism]
```
`--splits smoke,dev,heldout` picks splits (built in that order; truth holds only the splits of that run);
`--smoke-only`; `--workers` max 3. The generator refuses `--suffix`/`--repeats-per-position` into `scenes/`.
About 1.4-2.7 CPU s per frame (idle vs busy Mac).

## Truth contract (`screen-game-truth-v1`)
Per game: `id, split, seed, difficulty, cameraMode (fixed|jitter|drift), whiteAtBottom, startFen, frames[]`.
Per frame: `index, file, kind (start|move|repeat), fen (position shown), moveUci, moveSan, flags (capture,
enpassant, castle-k, castle-q, promotion, check), corners, disturbance {glare, hand, banding}, scene {...}`.
`corners` are always a8,h8,h1,a1 of the playing area, pixel centres at integer coordinates; with
`whiteAtBottom: false` a8 is bottom-right on screen. En passant carries `capture` and `enpassant`.
scenes-v2 adds `positionIndex` (0 = start, +1 per move, repeats share it) and `disturbance.sticky`.

## Content
- Round one: smoke (2 x 8 frames, easy, fixed), dev and heldout (12 games each, 30-42 frames, each
  position once plus ~10 % random repeats). heldout has since been scored: no longer untouched.
- Round two (scenes-v2): smoke2, dev2, heldout2 with new seeds and openings; every position (start
  included) is shown 3 times in a row (start/move + 2 repeats), games of 25-35 positions.
- All dev/heldout splits: 4 games per difficulty, every camera mode in every difficulty, 4 flipped games,
  one mid-game start; scripted openings force castling both ways, en passant and (under-)promotion,
  then seeded random legal play (legal, not sensible chess).
- Camera: fixed = identical homography; jitter = per-picture tremor < 1.4 % of board width; drift =
  smooth change up to ~15 %. Noise, blur, exposure, JPEG are fresh per picture.
- Glare / hand / banding only in medium and hard games, on a minority of pictures; never glare or hand
  on start-position pictures. Round two: about 30 % of disturbed positions are sticky (same glare spot
  or hand, fixed to the board, on all 3 pictures: what defeats a two-picture agreement guard); otherwise
  a redrawn glare moves >= 0.1 board width and a redrawn hand takes another corner.

## Round three: realism stress (`scenes-stress/`)
`nice -n 10 python3 -B $G --stress all --out $B/scenes-stress --workers 2` builds `stressdev` and `stressheld`
(never inspect recogniser results on stressheld): 12 variants x 3 games, 12-15 positions, 3 pictures per
position, easy photometrics, jitter camera, one flipped game per variant. Each game has
`stress {name, level}`; each changes ONE thing. New frame kind `transition` (mid-move only): one picture
BEFORE a position's settled pictures with the moving piece halfway; its `fen` is the position AFTER the
move, `transition: true`, `transitionMove` = move in progress. A pipeline must refuse it, never accept a
move from it. Old roots never contain it. `--limit-games N` builds only the first N games (tests).
Variant: imitates / does NOT capture:
- `baseline`: same seeds, lines, camera and noise as `style-unfamiliar` with the usual artwork (control).
- `style-unfamiliar`: an unknown piece set (slim pieces, start picture too) / real site artwork, shading.
- `style-flat`: large solid silhouettes, no outlines (~85% of square) as on chess sites / real site
  shapes, gradients, inner detail lines.
- `theme-colours`: brown/cream, blue/white and low-contrast gray (25 levels) boards / textured or
  wood-image boards, board borders.
- `last-move-highlight`: yellow-green 45% tint on from/to squares / other colours, check highlights,
  premove and selection highlights.
- `coordinates`: small rank digits and file letters in edge squares / other fonts, coordinates
  outside the board.
- `arrows-and-dots`: on ~30% of positions an orange arrow and move dots of a hovered piece, unrelated
  to the move (dots are pseudo-legal, ignore pins) / dragging a piece, capture rings, many arrows.
- `lens-distortion`: radial barrel distortion (edge bow 0.5, 1, 2% of board width); truth corners are
  the distorted corners, edges are curved so a 4-corner homography cannot be exact / tangential
  distortion, vignetting, per-device calibration.
- `moire`: screen pixel grid aliased into fringes, amplitude 3, 6, 12% / sub-pixel RGB stripes,
  colour moire, changes with focus.
- `motion-blur`: linear blur 3, 6, 12 px at a random angle per picture / rotation blur, rolling
  shutter skew, blur varying across the frame.
- `small-board`: board 10, 12, 14% of frame width (detector untested below 15%) / real
  optics at that distance (lens softness, compression).
- `mid-move`: every third position gets a transition picture (piece halfway, origin empty) / real
  animation easing, dragged pieces under a cursor, partially faded pieces.

## Test coverage
Schema; files exist at 1920x1080; sequence rules; every move re-checked by chess.js; flags vs SAN; split
counts and special-move minimums; camera bounds; pixel corner check on easy frames with a shifted-corner
negative control; v2: 3 distinct pictures per position, sticky vs moving disturbances; no seed or move
line shared across any two splits; determinism (legacy smoke, smoke2, one stress game). Stress: each
variant's effect is measured in the pictures (tint, ink, dots, fringes, edge sharpness, bow, width).

## Limits
All simulated: synthetic room, no real reflections or rolling shutter; stress variants are single
crude models of each effect. Scores here bound nothing about real camera footage.
