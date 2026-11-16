# Square reader v4.3 (experiment, 2026-11-16, simulated images only)
Same API as v3 (`calibrate`, `classify`, `occupancy_from_fen`, `CalibrationError`, `policy()`, `SQUARES`).
Code `scripts/recognition/occupancy_classifier_v4.py`, `VERSION = 'v4.3'` (sha256 `de58ef04...b474b`,
2026-11-16, 69 constants in `policy()`). v4.0 (`1e0830ba...63bbb`), v4.1 (`43ffc22a...973a3`) and v4.2
(`3d814e14...c97dd`) were each broken by an independent review (sections "v4.1 review fixes", "v4.2 second-review
fixes" and "v4.3 third-review fix"); copies are kept in `classifier-v4/round3/`, `round4/` and `round5/`. Harness `scripts/recognition/evaluate_classifier_v4.py`; tests
`python3 -B tests/occupancy_classifier_v4.py` (55 tests: every v3.1 case pointed at v4, solid pieces, highlights,
attacks, half-drawn pieces, start controls, and the three reviews' attacks in small form).
v3.1 (`c634a76d...`) stays frozen and stays the pipeline default; v4 is selectable with `--classifier v4`.
Outputs `/Users/alexmunzon/chess-builds/pipeline-2026-11-15/classifier-v4/` (v4.0: `round2/`, v4.1: `round3/`, v4.2: `round4/`, v4.3: `round5/`). Tuned on smoke, dev,
smoke2, dev2 and stressdev only; no `heldout*` or `stressheld` split was read, listed or scored.

## Why v4
v3.1 refuses two things common on chess sites. **Solid ("flat") pieces**: they fill ~85 % of the square and cover
v3's fixed edge strips and ring (`background-mismatch` on every start square); white solid pieces on cream squares
also show too small a brightness step for v3's edge cue, and their fill clips at 250. **Last-move highlights**: the
45 % yellow-green tint is neither a brightness factor nor added grey, so v3's lighting model leaves it unexplained.
Slim "unfamiliar" pieces stay refused (no readable fill; not attempted).

## What changed versus v3.1 (markers V4 A-E in the code)
- **A. Bare-board mask from the start picture.** Union of all start pieces' silhouettes (> 20 RGB from the board),
  grown 2 px; the lighting strips, the ring check and the clipped-ring test use only pixels outside it. If the mask
  leaves too few bare strip rows (< 20) or ring pixels (< 40), which moire, noise and lens bending cause, v3's fixed
  geometry is used and the normal start checks decide (round 2: without this fallback v4 lost starts v3 accepted;
  it is in use on dev-g02, dev-g05, dev2-g01 and dev2-g05, whose noise reaches the strips).
- **B. Edge cue.** RGB step instead of luminance step, counted out to the strips. Only on a square colour where a
  start piece fails v3's edge scale (solid white on cream), the scale becomes the RGB gap from that square colour to
  the nearer piece fill (floor 0.5 x contrast), stored as `edgeContrast`. Classic-style starts keep v3's scale.
- **C. Highlighted squares.** A disturbed square whose whole bare ring is one uniform colour is a tint candidate. It
  is read against that colour only if exactly two candidates form one overlay (same-colour squares: same tint;
  light + dark: opacity <= 0.6), each tint is >= 60 RGB from both fills and >= 40 from the other square colour,
  neighbours are calm, EMPTY also holds at 0.4x thresholds, and (round 2) the pair reads as exactly one empty square
  and one piece, as every last move leaves it; otherwise both are unknown.
- **D. Piece shape from the start.** A piece must stand on the base row of the start pieces of its colour on that
  square colour (+-4 px), with a base >= 0.75x as wide and a size within 0.6-1.35x. Round 2: the base row is the
  lowest row at least half as wide as the widest (stray noisy rows ignored), and a start is refused only if most of a
  kind's pieces miss the common base row (one noisy start square no longer refuses the start).
- **E. EMPTY needs a visible piece to be possible (round 2).** If local light or a tint has moved a square's own
  board colour so near a piece fill that the gap is below 0.6x the start's gap, a solid piece of that colour could be
  invisible there: unknown. Found by the attack test (a near-white tint the lighting model absorbed as glare hid a
  solid white pawn, read empty).

## v4.3 third-review fix (round 5)
The third review (`/Users/alexmunzon/chess-builds/review-classifier-v42-2026-11-16/`) proved one HIGH problem: rule G's
two bounds came from the start picture's noisiest empty square with no upper limit. One 25 RGB glare spot (sigma 18
px) on the empty d4 of the start, which the start checks accept, raised them from 16 / 3 RGB to 39.6 / 29 RGB, and
the second review's pale-layer and inset-box attacks came back on flat boards: 39 wrong squares (real pieces read
empty) on 14 boards, 0 with a clean start. Reproduced on v4.2 (`round5/rev3/logs/noisy_start_v42.out`,
`glare_threshold_v42.out`).
**Fix.** Start noise can now only tighten G, never loosen it. The strict distance is always 16 RGB (the start's
window noise no longer raises it). The move bound is still 3x the start's largest empty-square move, but clamped to
3-6 RGB (`MOVE_MIN`, new `MOVE_MAX`). A start noisier than that is accepted, not refused: its later empty squares that
move more than 6 RGB, or show pixels beyond 16 RGB, are simply unknown. Refusing would lose whole games on
development data, where 14 of 109 accepted starts (true and detected corners) had a move bound above 6 RGB (up to 71
RGB on dev-g02, whose start picture is lit); accepting with the caps is never confidently wrong because of G.
**Why 6 RGB.** It is twice the clean-start bound (3 RGB), well above the bare-board move of undisturbed empty squares
(2.2 RGB at the 99th percentile), and below the smallest layer move in the reviews' attacks (a layer 14 RGB from the
board colour at 49 % opacity moves it 6.9 RGB). Cost on v4.2's correct empty reads, true corners (`round5/move_cost_*.log`):
a 6 RGB ceiling loses dev 426 of 12,858, dev2 699 of 28,302, stressdev 133 of 36,449; 5 RGB would lose 552, 1,170 and
188, 3 RGB 1,098, 2,691 and 572.
**Other values learned from the start** (checked with one glare spot of 10-40 RGB on ten start squares, both styles,
`round5/start_glare_values.log`): the edge scale (`edgeContrast`) is already held between 0.5x and 1x contrast; the
piece faintness reference, size range, base width and layer opacity move by at most 13 % and keep natural limits
(a piece pixel is at least 40 RGB from the board; shares lie between 0 and 1). Not capped. One value is not bounded in
practice: the two-colour limit (`oppMax`). A 40 RGB glare spot on one black start piece (classic d7) raised it for
black pieces on light squares from 0 to 0.50, which loosens the two-colour rule for that kind for the game. It was
left as it is: development starts already reach 1.0 for classic white pieces and 0.24 for black ones, so one fixed
cap would either do nothing or cost real reads, and no attack has shown a wrong square from it. Listed under Limits.

Results (`round5/`): the third review's noisy-start script, 0 wrong squares on each of the 10 starts x 14 boards (flat
glare-d4-25: 0 of 14 boards, was 39 squares; 140 boards in all, v3.1 75 squares); glare script: bounds 16 / 3 on a
clean start, 16 / 6 on every glare start, 0 wrong squares at every glare level, start-only and fixed glare. Both earlier
reviews' attacks: the same totals as v4.2 (overlay 0 (12) of 350, banner 0 (13) of 160, shape 8 (55) of 490, full
layers 0 (45) of 192, partial 0 (36) of 280, faint 0 (111) of 80, piece over piece 59 (109) of 88, all others 0; the
same 27 squares on pictures nearly identical to a real position). Development splits (`round5/compare.log`): confident
wrong squares 0 outside mid-move pictures; regression 0 against v3.1 and against v4.2; starts unchanged (stressdev
28/36 true, 27/36 detected); highlighted squares 234 of 234. Cost, true corners: squares v3.1 reads that v4.3 leaves
unknown dev 2,797, dev2 6,241, stressdev 846 (v4.2: 2,255, 4,661, 442); v4.2 reads lost dev 542, dev2 1,580, stressdev
440, none gained. Tests 55 of 55; both new tests fail on the saved v4.2 (`round5/against_v42.log`).
Pipeline scorer, self-aware (`round5/pipe-*-v43/`): wrong accepted moves at two-picture agreement 0 on dev2 and 0 on
stressdev; at one picture 0 (dev2) and 5 (stressdev, the same mid-move pictures as before). Re-reviews per 100
positions: dev2 36.5 / 45.4 (agree 1 / 2; v4.2 34.1 / 43.3), stressdev 22.2 / 22.7 (v4.2 21.9 / 22.5). Starts dev2
12/12, stressdev 30/36.

## v4.2 second-review fixes (round 4)
The second review (`/Users/alexmunzon/chess-builds/review-classifier-v41-2026-11-16/`) proved:
1. **HIGH: layers close to the board colour still hid solid pieces.** A layer 16-25 RGB from the board colour,
   differing mainly in hue, at 49-75 % opacity, made solid white pieces on light squares read empty (74 wrong
   squares on 21 boards; a pale dialog: 17 on 6 of 80). v4.1 only looked at the part of the colour change its
   lighting model can express, and its 15 RGB bar had no margin. v4.1's "within 15 RGB" limit was wrong.
   **Fix G.** A layer of any colour L and opacity a squashes every piece under it by (1 - a) and moves the bare board
   by a |L - board|. In one square every board move is consistent with some layer (a = 1, L = the observed colour),
   so EMPTY now needs two things the start picture itself bounds: (1) the window is clear even at a strict distance
   (16 RGB, or twice the start's empty-window noise at the 99th percentile, whichever is larger; v4.3: always 16), so only a layer
   opaque enough to push the faintest start piece below that distance could hide it; and (2) the bare board, WITHOUT
   any lighting correction (strips and ring, fitted part plus leftover), moved less than 3x the largest move of the
   start's own empty squares (never less than 3 RGB; v4.3: never more than 6). What remains is a layer opaque enough to hide a piece AND
   within about 3 RGB (the start's noise) of the board colour: in one picture that is an empty square.
   Consequence, said plainly: on any board, an empty square under glare, banding or any other colour change beyond
   the start's noise is unknown. Lit pieces are still read.
   Any square whose bare board moved 40 RGB (FG_DISTANCE) or more is unknown whatever it reads (a promotion chooser
   or dialog with pieces drawn on top); this replaces v4.1's 50 %-opacity bound, which was inflated on light squares
   with little channel headroom and cost reads on undisturbed pictures.
2. **LOW: an opaque grey box inset in a dark square hides black pieces** (38 RGB from the dark square, below the 40
   RGB foreground line); v3.1 fails the same way. v4.1's doc wrongly said "within 15 RGB": the true v4.1 limit was
   about 40 RGB. In v4.2, G (1) catches it: the box is 38 RGB from the dark square, beyond the strict 16 RGB (the
   second review's partial-layer script, which includes this box: 0 wrong of 280 boards, v3.1 36). Remaining limit:
   an opaque box within the strict distance (16 RGB, or twice the start's noise) of the board colour, inset so the
   edge strips stay bare.
3. **LOW: a white piece drawn over a black piece read white.** **Fix.** A piece is unknown when its silhouette holds
   more opposite-colour pixels than the start pieces of its kind by more than max(0.03, 0.25 x their maximum)
   (classic pieces carry opposite-colour outlines). Not applied on highlighted squares (the artwork's board-coloured
   parts blend with the tint). Cost on real pieces: 0.2 % of dev and stressdev piece reads.
4. **LOW: ghosts at 0.59-0.60 opacity read as pieces.** **Fix.** The faintness line is 0.85x the faintest start
   piece's contrast (was 0.6). On dev and stressdev, real pieces measured 0.94 at the 1st percentile and 0.84 at the
   0.1th; 0.85 refuses 0.2 % of real piece reads. Ghosts above 0.85 opacity still read as pieces.
5. **LOW: starts with boxes on two squares' strips, or a banner across one rank, were accepted.** **Fix.** A pixel
   becomes learned piece area only if start pieces of BOTH colours cover it (each artwork shape appears in both
   colours on a start). Cost: the stressdev coordinates game whose file letters sit on one side's squares is refused
   again (3/3 -> 2/3, as v3.1).

Both reviews' attack scripts re-run with v4.2 from copies (`round4/rev1/`, `round4/rev2/`, totals
`round4/attacks_summary.txt`). Squares where v4.2 is confidently wrong (v3.1 in brackets): first review: general 0
(0) of 480 boards, overlay 0 (12) of 350, banner 0 (13) of 160, start 0 (0) of 54, tint 0 (0) of 216, shape 8 (55)
of 490; second review: full-square layers 0 (45) of 192, partial layers 0 (36) of 280, gradient 0 (0) of 60, faint
ghosts 0 (111) of 80, displaced 0 (0) of 96, pale dialog 0 (0) of 80, start probes 0 of 144, piece over piece 59
(109) of 88. Squares where v4.2 is wrong and v3.1 was unknown, correct or had no start: 27, all on pictures identical
or effectively identical to a real position: 4 in the first review's shape script (a knight or bishop drawn at
offset 0, exactly standing), 23 in the second's piece-over-piece script (a solid white piece drawn over a black
pawn or queen at offsets of 0-3 px, where 0-2.3 % of the silhouette shows the lower piece; list in
`round4/basemix_remaining.txt`). Every new test fails on the saved v4.1 (`round4/against_v41.py`, 5 of 5).

## v4.1 review fixes (round 3)
The review (`/Users/alexmunzon/chess-builds/review-classifier-v4-2026-11-16/`) proved five problems in v4.0:
1. **See-through layers hid solid pieces.** A light grey or beige layer at 50-60 % opacity over a solid white piece
   on a light square read "empty" (black pieces at 80-90 %): the lighting model took the layer for glare, and E only
   looks at where the board colour went, not at how much the layer squashed the piece. **Fix F.** At the start, v4.1
   learns per square colour the least layer opacity that would wash some start piece below PIECE_MIN_FG
   (`layerHide`: a layer of opacity a shrinks every colour difference under it by 1 - a). An EMPTY square is
   unknown if its board colour moved by at least `layerHide` x 15 RGB (a layer at least 15 RGB from the board
   colour that is opaque enough to hide a piece moves it that far) or if the least opacity ANY layer colour needs
   for the observed move (each channel's headroom in the RGB cube) reaches `layerHide`. Any square whose move needs
   a layer at least 50 % opaque is unknown whatever it reads (a promotion chooser or dialog is drawn on such a layer).
   A piece must show at least 0.6x the strongest contrast of the faintest start piece of its kind (a piece seen
   through a layer, a faded drag ghost: finding 4).
2. **Pieces drawn too low still looked based.** The shape band stopped at row 61. **Fix D.** The shape is measured
   over the whole tile below row 3, counting only pixels far from every blend of the two board colours (so the
   blurred border with a neighbour square or a corner error does not look like a piece); base row within 2 px (was
   4), base centre within 3 px (new; width and centre also measured without the local lighting correction, which
   otherwise "corrects away" the part of a piece pushed into the side strips), no piece rows more than 2 px below
   the base, and the base's white/black mix within 0.3 of the start pieces' (a piece held above another piece shows
   the lower piece's base).
3. **Promotion chooser** (inherited from v3.1): fixed by F's 50 % rule and D's base checks.
4. **Drag ghost** read as a piece: fixed by the contrast rule in F.
5. **Cursor or tooltip on the start learned into the mask** (v3.1 refuses those starts). **Fix A.** A pixel joins
   the mask only if two or more start squares cover it; every piece shape of a full start set appears on two or
   more squares. Flat starts with a cursor fully inside a piece are still accepted (v3.1 refuses every flat start
   for its style; the same colour check refuses the classic version); the cursor only slightly changes that one
   start piece's learned statistics (not shown to cause a wrong square).

Review attacks re-run with v4.1 on copies of the reviewer's scripts (`round3/review-copy/`, logs there), squares
where v4.1 is confidently wrong (v3.1 in brackets): general 0 (0) of 480 boards; overlay 0 (12) of 350; banner 0 (13)
of 160; start 0 (0) of 54 boards after accepted starts; tint 0 (0) of 216; shape 8 (55) of 490. Of the 8, 4 are on
classic drag pictures where v3.1 is also wrong, and 4 are on flat pictures where a knight or bishop is drawn exactly
on a square (offset 0, pixel-identical to a piece standing there; the script's answer key still has the piece
elsewhere); v3.1 has no flat start. Squares where v4.1 is wrong and v3.1 was unknown, correct or had no start: 4
(those 4 offset-0 pictures). The base probe: v4.1 refuses every offset from 4 px on, both styles.
Every new test fails on the saved v4.0 (`round3/against_frozen.py`, log `against_frozen.log`, 6 of 6 fail).

## v4.0 results (round 2; superseded by "v4.1 results" below)
Harness, square by square, true / detected corners; wrong / unknown / correct.
| split | v3.1 starts | v3.1 | v4 starts | v4 |
|---|---|---|---|---|
| smoke | 2/2, 2/2 | 0 / 0 / 896 both | 2/2, 2/2 | 0 / 0 / 896 both |
| dev | 12/12, 12/12 | 0 / 1618 / 25326; 0 / 1543 / 25273 | 12/12, 12/12 | 0 / 1701 / 25243; 0 / 1617 / 25199 |
| smoke2 | 2/2, 2/2 | 0 / 0 / 2944 both | 2/2, 2/2 | 0 / 0 / 2944 both |
| dev2 | 11/12, 11/12 | 0 / 3955 / 55629 both | 11/12, 11/12 | 0 / 3807 / 55777 both |
| stressdev | 24/36, 24/36 | 11 / 586 / 61419; 11 / 585 / 61420 | 29/36, 28/36 | 11 / 429 / 73352; 11 / 418 / 71123 |

v3.1 reproduces its doc exactly on dev and dev2. stressdev starts per variant (first start picture, true corners),
v3.1 -> v4: style-flat 0/3 -> 3/3, coordinates 2/3 -> 3/3, small-board 2/3 -> 3/3 (detected corners 2/3 both),
style-unfamiliar 0/3 both, lens-distortion 1/3 both, moire 2/3 both, motion-blur 2/3 both, all others 3/3 both.
(The orchestrator's 27/36 for v3 came from the pipeline, which may use several start pictures; the harness uses the
first.) Highlighted squares: v3.1 0 of 234 read (all unknown), v4 234 of 234 correct, 0 wrong (per corner source).
- **Confident wrong squares: 0 on smoke, dev, smoke2, dev2.** stressdev: 11 per corner source, all on mid-move
  transition pictures and all equal to what is DRAWN there (the answer key holds the position after the move; a piece
  moving two squares in a line is drawn centred on the middle square, and a captured piece is still drawn): v3.1 has
  the same 11. No reader can be right on those from one picture; the pipeline's two-picture rule handles them.
- **No regression:** on frames both versions score, v4 is never wrong where v3.1 was correct or unknown (0 squares
  on smoke, dev, smoke2, dev2 and stressdev). Squares v3.1 read and v4 leaves unknown: dev 199 (E: glare-lit empty
  squares; D: classic black pieces with uneven bases), dev2 562, stressdev 125; newly read: dev 42, dev2 858,
  stressdev 471 plus the newly accepted games.

## v4.0 pipeline scorer (round 2, self-aware mode, simulated images only)
`evaluate_screen_pipeline.py --classifier v4 --agree 1,2` (outputs `round2/pipe-dev2-v4/`, `round2/pipe-stressdev-v4/`).
- dev2: wrong accepted moves 0 with two-picture agreement and 0 with one picture (stale-unchanged 0); starts 12/12
  (11 on the first picture); re-reviews per 100 positions 25.2 (agree 1) / 32.3 (agree 2); v3.1's documented figures
  were 23.7 / 31.5.
- stressdev: wrong accepted moves **0 with two-picture agreement**, **5 with one picture**; all 5 are on mid-move
  transition pictures where the half-drawn piece sits exactly on a legal destination (f2f3, e7e6, g2g3, c8e6, h7h6),
  so one picture shows a real legal position. Starts 30/36 (28 on the first picture); re-reviews per 100 positions
  6.4 / 7.0; squares 72576: 72082 correct, 11 confident wrong (the mid-move ones above), 483 unknown.

## v4.2 results (round 4; harness `round4/runs/`, comparison `round4/compare.log`, pipeline `round4/pipe-*-v42/`)
| split | v3.1 (true corners) | v4.1 (true) | v4.2 (true; detected) |
|---|---|---|---|
| smoke | 0 / 0 / 896 | 0 / 0 / 896 | 0 / 1 / 895 both |
| dev | 0 / 1618 / 25326 | 0 / 3539 / 23405 | 0 / 3863 / 23081; 0 / 3767 / 23049 |
| smoke2 | 0 / 0 / 2944 | 0 / 0 / 2944 | 0 / 0 / 2944 both |
| dev2 | 0 / 3955 / 55629 | 0 / 7532 / 52052 | 0 / 8282 / 51302; 0 / 8261 / 51323 |
| stressdev | 11 / 586 / 61419 | 11 / 609 / 73172 | 11 / 859 / 70682; 11 / 1034 / 68267 |
- Confident wrong squares against what is drawn: 0 on every split apart from the 11 mid-move squares per corner
  source on stressdev (same as v3.1, v4.0, v4.1). No regression: 0 squares where v4.2 is wrong and v3.1 was not.
- stressdev starts 28/36 true, 27/36 detected (v4.1: 29, 28): the coordinates game with file letters on one side's
  squares is refused again (2/3, as v3.1); style-flat 3/3, small-board 3/3 true. Highlighted squares 234 of 234.
- **Cost in reads** (true corners): versus v3.1, squares v3.1 read and v4.2 leaves unknown: dev 2255, dev2 4661,
  stressdev 442 (v4.1: 1934, 3887, 232). Versus v4.1: dev 762 lost / 438 gained, dev2 1750 / 1000, stressdev 263 / 13.
  The new losses are lit empty squares (rule G) and 0.2 % of real pieces (faintness and two-colour rules); the gains
  come from replacing v4.1's opacity bound. Flat boards stay readable: stressdev style-flat 3/3 starts, its
  pictures have no lighting disturbance.
- Pipeline scorer, self-aware: wrong accepted moves at two-picture agreement 0 on dev2 and 0 on stressdev; at one
  picture 0 (dev2) and 5 (stressdev, the same mid-move pictures). Re-reviews per 100 positions: dev2 34.1 / 43.3
  (agree 1 / 2; v4.1 34.1 / 39.5), stressdev 21.9 / 22.5 (v4.1 14.4 / 13.9). Starts dev2 12/12, stressdev 30/36.

## v4.1 results (round 3; harness `round3/runs/`, pipeline `round3/pipe-*-v41/`; superseded)
| split | v3.1 (true corners) | v4.0 | v4.1 (true; detected) |
|---|---|---|---|
| smoke | 0 / 0 / 896 | 0 / 0 / 896 | 0 / 0 / 896 both |
| dev | 0 / 1618 / 25326 | 0 / 1701 / 25243 | 0 / 3539 / 23405; 0 / 3438 / 23378 |
| smoke2 | 0 / 0 / 2944 | 0 / 0 / 2944 | 0 / 0 / 2944 both |
| dev2 | 0 / 3955 / 55629 | 0 / 3807 / 55777 | 0 / 7532 / 52052; 0 / 7504 / 52080 |
| stressdev | 11 / 586 / 61419 | 11 / 429 / 73352 | 11 / 609 / 73172; 11 / 803 / 70738 |
- Confident wrong squares against what is drawn: 0 on every split; the 11 per corner source on stressdev are the
  mid-move pictures (same as v3.1 and v4.0). No regression: 0 squares where v4.1 is wrong and v3.1 was not (common
  frames, all five splits, both corner sources).
- Starts and highlights unchanged from v4.0: stressdev 29/36 (true), 28/36 (detected); per variant as v4.0
  (style-flat 3/3, coordinates 3/3, small-board 3/3 true); highlighted squares 234 of 234 correct per corner source.
- **Cost.** Squares v3.1 read that v4.1 leaves unknown (true corners): dev 1934, dev2 3887, stressdev 232 (v4.0: 199,
  562, 125). Mostly F on glare- and banding-lit squares (dev reason counts, true corners: piece-could-be-under-a-layer 1798, possible-see-through-layer 1510, a
  layer of >= 50 % opacity) and D's tighter base on classic pieces. Pipeline re-reviews per 100 positions rise: dev2 34.1 /
  39.5 (agree 1 / 2; v4.0 25.2 / 32.3), stressdev 14.4 / 13.9 (v4.0 6.4 / 7.0).
- Pipeline scorer, self-aware: dev2 wrong accepted moves 0 (agree 2) and 0 (agree 1); stressdev 0 (agree 2) and 5
  (agree 1, the same 5 mid-move pictures as v4.0). Starts 12/12 dev2, 30/36 stressdev.

## Where each threshold came from (development data only)
v3.1's 39 constants are unchanged. Draft first guesses (round 1, clean boards) kept after the round-2 runs showed no
wrong square: SIL_DISTANCE 20 (half FG_DISTANCE), MASK_GROW 2, STRIP_MIN_ROWS 20, RING_MIN_PIXELS 40, TINT_MAX_ROW_DEV,
TINT_MIN_FILL_DIST 60 (1.5x FG_DISTANCE), TINT_MIN_OTHER_DIST 40, TINT_PAIR_TOL, TINT_MAX_ALPHA 0.6,
TINT_PAIR_RESIDUAL, TINT_EMPTY_SCALE 0.4, BASE_MIN_RUN 4, BASE_ROW_TOL 4, BASE_MIN_WIDTH 0.75, SIZE_RANGE 0.6-1.35.
Round 2: BASE_MIN_SHARE 0.5 (dev-g02: classic black pieces lost reads to a few stray rows below the base; 49 of a
60-square sample came back); EDGE_CONTRAST_MIN 0.5 (a floor; used only by the 3 stressdev flat starts, light squares, 0.76-0.78x; no other development start); EMPTY_FILL_KEEP
0.6 (solid white on cream has a start gap of ~72-75 RGB; 0.6x keeps ~43-45 > FG_DISTANCE 40, so above the line a
solid piece still counts as foreground; cost on dev, true corners: 83 squares). No threshold was loosened to
pass a test.
v4.1: BASE_ROW_TOL 2 and BASE_COL_TOL 3 (the review's standard: a piece more than 3 px off is not standing; at 3 px the
blurred tile edge already hides 1 px of a cut-off base), BASE_COLOUR_ROWS 6 / BASE_COLOUR_TOL 0.3, PIECE_MIN_CONTRAST
0.6 (a 50 % layer or a 35 % ghost halves contrast or worse), LAYER_MAX_OPACITY 0.5 (the promotion chooser needs
~0.85), LAYER_COLOUR_MIN_DIST 15 (the review's cream layer (240, 230, 200) is 16 RGB from the light square; 15 x
`layerHide` stays above the undisturbed noise: board-colour moves on undisturbed dev empties are at most 2.2 RGB,
99th percentile), MASK_MIN_SQUARES 2. These were set from the review's attacks and checked on development data;
they cost reads (see v4.1 results).

## Tests and mutation check
v4.3: 55 of 55 pass; the 2 new third-review tests (glare on an empty start square followed by the pale-layer and inset-box attacks; the bounds never above 16 / 6 RGB for any start noise) both fail on the saved v4.2 (`round5/against_v42.py`). v4.2: 53 of 53 pass; the 5 new second-review tests all fail on v4.1. The v3.1 banding test (>= 56 of 64 squares
read under 5 % banding) was changed: under rule G, empty squares under banding are unknown by design; it now asks
for >= 28 of 32 pieces read and no wrong square. v4.1: 48 of 48 passed; the 6 review tests all failed on v4.0. v4.0 round 2: 42 of 42 passed. Each guard was switched off in a copy of the module (`round2/mutation.py`, log `round2/mutation.log`):
8 of 9 guards make their attack test fail. TINT_MIN_FILL_DIST (60 -> 0) is not caught: E (EMPTY_FILL_KEEP) already
refuses the same attack, so it is a margin, not a proven guard. Changed draft tests: the two style-switch tests
demanded that every piece be refused after a classic <-> flat switch; v4 reads them correctly instead (it did not
refuse them with the round-1 base rule either), so they now check the safety rule (no wrong square). The "opaque pair light+dark"
case used e4 and f3, which are both light squares; it is kept as "both light" and a real light+dark case (e4, e5)
was added.

## Limits
- Simulated pictures, two piece styles, one renderer; slim pieces refused; no glare or hands in stressdev. The
  reviews' attacks are crude models (one renderer, flat layers, one cursor shape).
- v4.3 answers unknown for every empty square whose bare board moved beyond the start's noise (glare, banding,
  colour shifts), and never allows more than 6 RGB whatever the start: a large cost on lit pictures, the price of
  refusing see-through layers. Banding alone costs empty squares even on a clean start (third review, the v3.1
  banding case): 2 % banding loses 4 of 32 empty squares, 3 % loses 9, 5 % loses 12 (period 100 px) or 24 (period 40
  px), 10 % all 32; pieces are still read and no square is wrong. A start that is itself lit or noisy makes later
  empty squares unknown more often (the caps hold, so it never makes them easier to read).
- Blind spot of rule G: a layer opaque enough to hide a piece AND close enough to the board colour that the bare
  board moves less than the move bound looks like an empty square in one picture. On a clean start that bound is
  3 RGB; on any start it is at most 6 RGB. Hiding a piece needs roughly 80-95 % opacity, so the layer must be within
  about 3-4 RGB of the board colour on a clean start and at most about 8 RGB on any start. Before v4.3 a noisy start raised this without limit (the third review's
  finding); the earlier "within about 3 RGB" held only for a clean start. Likewise an opaque box within 16 RGB of the
  board colour inset inside a square so that the edge strips stay bare reads empty (v3.1 reads such boxes empty up
  to about 40 RGB).
- An opaque cell close to the board colour with a full-size piece drawn on it (for example a promotion chooser in
  board-like colours) is read as that piece standing there, in every version: third review, 600 wrong squares for
  v4.2 and 397 for v3.1 on 320 classic boards. The cell is board-like, so nothing marks it as a layer. Not fixed.
- A black piece drawn over a white piece is not caught by the two-colour rule (it was built for the white-over-black
  case): flat black over white gave 77 wrong squares on 132 boards in the third review (v3.1 has no flat start); the
  lower piece shows only as thin rims, visible on zoom. The rule's limit for classic white pieces is near 1 already
  (their outlines are dark), and one glare spot on a black start piece can raise the limit for black pieces (0 to 0.50
  measured), so the rule is a weak guard in both directions. A layer exactly over one square in a
  site's highlight colour, paired with a real highlight, is read as the highlight (V4 C's limit below); highlighted
  squares are exempt from rule G and from the two-colour check.
- Ghosts above 0.85 opacity read as pieces; a piece drawn over another that hides it almost fully (<= ~2 % of the
  silhouette shows the lower piece) reads as the upper piece.
- A piece drawn exactly on a square (a drag at offset 0, a mid-move piece centred on a square) is read as standing
  there: the picture is identical to a real position. The two-picture rule and the move legality check are the
  defence.
- A cursor fully inside a solid start piece is accepted (see fix 5).
- Strong glare and banding now cost many reads (F cannot tell additive light from a layer in one square).
- A box of exactly a site's highlight colour drawn inside one square (spilling <= 3 px), paired with a real
  highlight, looks exactly like that site's highlight in one picture; a hidden piece then reads empty. The pipeline's
  legality check and two-picture rule are the defence.
- Squares a mid-move piece is drawn centred on read as that piece (identical to a real position).
- E and D cost some reads on classic pieces under glare and on classic black pieces with uneven bases.
