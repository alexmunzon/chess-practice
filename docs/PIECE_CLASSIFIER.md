# Piece-type reader v1 (feasibility prototype, 2026-11-16, simulated images only)

**Question:** can this build tell WHICH piece stands on a square (pawn, knight, bishop, rook, queen, king),
so that two same-colour pieces swapped or substituted are noticed?

**Answer:** on simulated screen boards, yes, with named work before it is real. Of 71,682 occupied
squares on the three report splits (smoke2, dev2, stressdev, never tuned on) the reader named **0 wrongly**,
named 67,208 correctly and said "unsure" on 4,474 (6.2 %). Every constructed same-colour swap and
substitution was either noticed or met with "unsure"; **none was missed** (0 of 7,218 swaps, 0 of 7,218
substitutions). All numbers are simulated pictures scored on a Mac with the TRUE board corners; nothing
here was measured on a real camera, a real screen or real piece artwork. It is not wired into the app or
the pipeline.

## Code and commands
- Reader: `scripts/recognition/piece_classifier_v1.py` (frozen for the report runs: sha256 `e5c31e2e...44523`).
- Tests: `python3 -B tests/piece_classifier_v1.py` (11 tests, about 5-15 s, renders its own boards; one
  test also reads two smoke pictures if the scene data is present).
- Evaluation (the only code that reads truth; refuses held-out splits and `ORCHESTRATOR_HELDOUT_RUN`):
  `python3 -B scripts/recognition/piece_classifier_v1.py evaluate --scenes ROOT --split NAME --out DIR [--dump-squares]`
- Outputs and logs (outside the repo): `/Users/alexmunzon/chess-builds/piece-classifier-2026-11-16/`
  (`final/` = the frozen runs, `fit/` and `fit2/` = the two tuning runs on dev, `CHECKLIST.md`).

## Data (step 1)
Truth in every split gives a full FEN per picture, so piece types are known for every square.
| split | role | games | pictures | start pictures | piece style |
|---|---|---|---|---|---|
| smoke | fit | 2 | 16 | 2 | the project's one flat 2D set (`scripts/simulation/appearance.py`) |
| dev | fit | 12 | 433 | 12 | same set |
| smoke2 | report | 2 | 48 | 6 | same set |
| dev2 | report | 12 | 1,047 | 36 | same set |
| stressdev | report | 36 | 1,473 (12 mid-move pictures skipped) | 108 | same set, except 3 games `style-unfamiliar` (slim pieces) and 3 `style-flat` (solid silhouettes) |

dev and dev2 each have 4 flipped games (Black at the bottom), 1 mid-game start, 3 or 2 promotions
(dev: Q, N, N; dev2: Q, B). Start pictures never carry glare or a hand. All 64 report and fit starts
contained all 12 piece kinds.

## Method (step 2)
Screen pieces are drawn images: the same artwork appears every time a piece stands on a square. So the
reader learns each game's own piece shapes from the human-reviewed start picture(s), where the rules of
chess fix every piece's identity, and needs no outside data or training set.
1. **Rectify.** The four board corners (a8, h8, h1, a1) map the board onto a 288 x 288 grid
   (36 px per square), area-averaged, laid out as on screen so pieces stand upright even on a flipped
   board. Squares whose pixels fall outside the image are "unsure".
2. **Learn (start).** Background colour of light and dark squares = median of the start's empty squares.
   Each piece picture is copied onto both square colours (pixels close to the original background are
   swapped for the other background) and averaged per piece kind: 12 shapes x 2 square colours. All
   reviewed start pictures are averaged (1 in round-one games, 3 in round-two and stress games).
3. **Read (later pictures).** Each square is compared with the 12 shapes for its square colour and with
   "no piece", allowing a shift of up to 2 px (5.5 % of a square), a brightness gain of 0.6-3.0 and a colour
   offset per square (so global lighting changes do not matter).
4. **Decide.** The best match is named only if (a) the second-best fits at least 2.0 x worse (margin),
   (b) the best fit is good (mean residual at most 0.06 x board contrast squared), (c) its gain is inside
   the limits, and (d) it is a piece. If "no piece" fits best the answer is "unsure", never "empty":
   occupancy belongs to the square reader (`occupancy_classifier_v3.py`), and a hand can hide a piece fully.

Uses at runtime only the pictures, the corners and the reviewed start position; truth is read only by
the `evaluate` subcommand for scoring.

**Tuning (smoke + dev only).** Two dev runs changed two things: the gain ceiling 1.7 -> 3.0 (the first
run abstained on 339 squares, every one a correct best match at the ceiling) and "empty" became "unsure"
(the first two runs read 3 hand-covered pieces as empty). Margin 2.0 was the first value tried; the dev
sweep showed margin 1.5 would have let 6 wrong readings through, 2.0 lets 0. Then frozen and run once on
smoke2, dev2 and stressdev.

## Results on the report splits (step 3; true corners; occupied squares; n of m)
| split | correct | named wrongly | unsure |
|---|---|---|---|
| smoke2 | 1,344 of 1,344 | 0 of 1,344 | 0 of 1,344 |
| dev2 | 25,619 of 28,257 | 0 of 28,257 | 2,638 of 28,257 |
| stressdev | 40,245 of 42,081 | 0 of 42,081 | 1,836 of 42,081 |
| fit: dev (for comparison) | 10,719 of 11,401 | 0 of 11,401 | 682 of 11,401 |

Empty squares named as a piece: 0 of 1,344 (smoke2), 0 of 36,447 (dev2), 0 of 44,511 (stressdev).

**By condition** (a picture with a hand counts as hand, else glare, else banding; stress games by variant):
| split / condition | correct | wrong | unsure |
|---|---|---|---|
| dev2 clean | 17,122 of 17,786 | 0 | 664 |
| dev2 glare | 3,094 of 3,630 | 0 | 536 |
| dev2 refresh banding | 2,228 of 2,694 | 0 | 466 |
| dev2 hand over board | 3,175 of 4,147 | 0 | 972 |
| dev2 blur sigma < 0.5 / 0.5-1 / >= 1 | 8,966 of 9,011 / 9,107 of 9,717 / 7,546 of 9,529 | 0 / 0 / 0 | 45 / 610 / 1,983 |
| stressdev baseline (clean) | 3,426 of 3,426 | 0 | 0 |
| stressdev lens distortion 0.5 % / 1 % / 2 % | 1,176 of 1,188 / 744 of 1,314 / 167 of 1,131 | 0 | 12 / 570 / 964 |
| stressdev motion blur 3 / 6 / 12 px | 1,272 of 1,272 / 1,230 of 1,230 / 1,095 of 1,305 | 0 | 0 / 0 / 210 |
| stressdev small board (10-14 % of frame) | 3,489 of 3,498 | 0 | 9 |
| stressdev style-unfamiliar | 3,426 of 3,426 | 0 | 0 |
| stressdev style-flat | 3,348 of 3,375 | 0 | 27 |
| stressdev theme colours (brown, blue, low-contrast grey) | 3,405 of 3,405 | 0 | 0 |
| stressdev arrows and dots | 3,514 of 3,558 | 0 | 44 |
| stressdev last-move highlight / coordinates / moire / mid-move | 3,669 / 3,234 / 3,531 / 3,519, all of all | 0 | 0 |

**By piece type** (white + black; correct of all, unsure; wrong is 0 everywhere):
| type | dev2 | stressdev |
|---|---|---|
| pawn | 12,349 of 13,782 (1,433 unsure) | 19,679 of 20,838 (1,159) |
| knight | 3,297 of 3,468 (171) | 5,041 of 5,241 (200) |
| bishop | 2,988 of 3,537 (549) | 4,913 of 5,229 (316) |
| rook | 3,346 of 3,651 (305) | 5,260 of 5,394 (134) |
| queen | 1,674 of 1,797 (123) | 2,649 of 2,673 (24) |
| king | 1,965 of 2,022 (57) | 2,703 of 2,706 (3) |

Real promotions (truth moves, later pictures of the promoted piece): dev2 queen 6 of 6 read Q, bishop
under-promotion 8 of 9 read B and 1 unsure; dev (fit) Q 1 of 1, N 6 of 6.

**Time per picture** (rectify + read, Python, one core; the Mac's load average was 12-70 during the runs,
so these are pessimistic): median 388 ms (smoke2), 362 ms (dev2), 386 ms (stressdev); 95th percentile
467 / 820 / 972 ms. Picture loading is not included.

## The safety hole: same-colour swaps and substitutions (step 4)
Constructed inside each scored picture: up to 3 pairs per picture of same-colour, different-kind pieces
that stand on squares of the same colour. **Swap** = the two square pictures exchanged; **substitution** =
square B shows A's piece. The claimed position is the old (true) one. "Noticed" = the reader names something
on a changed square that contradicts the claim; "missed" = both changed squares confidently read as the
claim; "unsure" = otherwise. "Unchanged" is the same check on the untouched picture (false alarms).
| split | swaps noticed / missed / unsure | substitutions noticed / missed / unsure | unchanged: false alarm |
|---|---|---|---|
| smoke2 | 126 / 0 / 0 of 126 | 126 / 0 / 0 of 126 | 0 of 126 |
| dev2 | 2,900 / 0 / 133 of 3,033 | 2,738 / 0 / 295 of 3,033 | 0 of 3,033 |
| stressdev | 3,978 / 0 / 81 of 4,059 | 3,892 / 0 / 167 of 4,059 | 0 of 4,059 |

Limit of this test: the swapped pictures are pixel exchanges inside one picture, so they test whether the
reader tells the shapes apart, not whether a freshly drawn piece looks the same. Pairs on squares of
different colours are not constructed. The real promotions above are the only naturally drawn substitutions.

## Where it fails or is close to failing
- **Margin headroom.** On squares where the best match was the wrong piece (blocked), the largest margin
  was 1.68 on dev (fit; white queen read as knight on a flipped game, 17 pictures of d2), 1.19 on dev2 and
  1.35 on stressdev, against the 2.0 gate. The dev case is INFERRED to come from step 2: the white queen
  appears at the start only on a light square, and copying a white piece onto a dark square is imprecise.
- **Lens distortion** (curved board edges): at 2 % bow 964 of 1,131 squares are unsure; a 4-corner warp
  cannot straighten the board, so pieces sit off-grid beyond the 2 px shift. Safe, but useless there.
- **Hand, glare, heavy blur** cost 15-23 % unsure on dev2 (glare 15 %, banding 17 %, blur sigma >= 1 21 %, hand 23 %); the near-misses there are pawns read as bishop or
  king under a hand (all blocked).
- **Piece kinds missing from the start (not tested).** If a kind is absent at the start (mid-game start
  without queens, or a promotion to a kind not on the board), the reader has no shape for it and could
  name the nearest other kind confidently. No development or report game had this case. INFERRED risk.
- **True corners only.** Detected corners (the pipeline's real input) were not used here.

## Recommendation
**Usable with named work, for boards on a screen.** The shape-learning approach fits drawn piece sets well:
0 wrong of 71,682 occupied report squares and 0 missed swaps, with "unsure" carrying the difficult cases.
Named work before it could guard the app:
1. Run it with detected corners and the pipeline's own orientation lock (same splits), and on held-out data
   scored once by the orchestrator.
2. Refuse to name a kind that the start did not show; treat a promotion as "needs review" until the new
   kind is seen in a reviewed picture. Add a test for it.
3. Learn shapes on both square colours (for example from the first reviewed picture after a piece has
   moved to the other colour) to remove the template-copy weakness behind the dev queen near-miss.
4. Decide how the pipeline uses it: a contradiction between the piece reading and the tracked position
   should withhold advice and ask for review, never move the tracker by itself.
5. Port to Swift and measure on the phone (the Python reader takes about 0.3-0.4 s per picture on a busy Mac).
6. Real screen footage: real site artwork, anti-aliasing, animations, piece-drag shadows, real lens
   distortion (needs a curved-edge correction or per-square alignment) and moire from a real camera.

**What a real camera changes.** On a real screen the method's key assumption mostly holds (a site draws
the same picture for a piece every time), so the main new risks are optics: lens distortion, focus, moire,
reflections and lower resolution per square. On **physical pieces** this method is not feasible: a 3D piece
looks different on every square and from every angle, pieces hide each other, and tall pieces lean into
neighbouring squares. That needs a trained model and real labelled photographs, which this project does not
have.

All results: simulated pictures, on a Mac, true corners, not camera evidence.

# Piece-type reader v2 (2026-11-16, simulated images only)

**Why v2.** An independent review reproduced every v1 number above and then made v1 confidently name wrong
pieces in six ways: a dirty start picture (arrow or glare learned into a shape), kinds learned from one square or
never shown, mid-move pictures, heavy picture damage, and tests that did not catch removed safety gates. v2 keeps
v1's method and adds rules that each close one of those holes. v1 (`piece_classifier_v1.py`, sha256
`e5c31e2e...44523`) is unchanged so the two can be compared; the v1 sections above keep their numbers.

## Code and commands
- Reader: `scripts/recognition/piece_classifier_v2.py`. Tests: `python3 -B tests/piece_classifier_v2.py`
  (22 tests, about 10-15 s).
- Evaluation: `python3 -B scripts/recognition/piece_classifier_v2.py evaluate --scenes ROOT --split NAME --out DIR`
  (refuses held-out splits and `ORCHESTRATOR_HELDOUT_RUN`; now also scores mid-move pictures and the guard).
- Outputs, tuning scripts, reviewer-attack copies and logs (outside the repo):
  `/Users/alexmunzon/chess-builds/piece-classifier-v2-2026-11-16/` (`final/` = report runs, `fit2/` = dev fit
  runs, `logs/`, `atk/` = the reviewer's attack scripts pointed at v2 by `atk/run_v2.py`, `mutation_v2.py`).

## What changed and why
1. **Start cleanliness.** Before learning, the start picture must be explained by the reviewed position. (a) Every
   empty square must be flat: the 98th percentile of |pixel - square median| over its central 64 % must stay under
   8 x the picture noise + 0.12 x board contrast (noise = robust spread of neighbouring-pixel differences on the
   empty squares, so a noisy or blurred camera does not trip it). (b) Every piece must agree with its siblings of
   the same kind (8 pawns, 2 rooks, ...): its residual against the mean shape of the others, under the usual gain,
   offset and shift, must stay under 15 x noise^2 + 0.035 x contrast^2 (kinds with 3 or more squares) or
   100 x noise^2 + 0.07 x contrast^2 (kinds with 2 squares, compared across square colours, less precise).
   If either fails the reader refuses to learn: state `no-reference`, every answer `unsure` (reason
   `no-reference`); the guard says "cannot tell" everywhere until a clean start is reviewed. A first idea, that the
   white and black shapes of a kind must overlap, was dropped: the classic set's white and black kings overlap only
   0.47-0.79 on clean starts.
2. **Thin evidence.** The calibration records how many start squares each kind was learned from. A kind learned from
   fewer than 2 squares is never named (reason `thin-evidence`). In the standard start that is both kings and
   both queens, so v2 never names a king or queen; this is the brief's rule taken literally and is the main cost
   (see the cost table). A thin kind is also an unreliable runner-up: its shape is imprecise, so its residual can
   be inflated and make another kind look clear; any thin kind must therefore fit at least 3.0 x worse than the
   winner (`thin-runner-up`), against 2.0 for well-evidenced kinds. If any kind of one colour was never shown at
   the start, no piece of that colour is named (`kind-set-incomplete`): the missing kind could be the answer and
   the reader has no shape to rule it out. The gain floor (0.6) keeps white and black apart, so the other colour
   is still named.
3. **Mid-move confirmation.** A piece sliding e2-e4 is drawn exactly centred on e3 half-way; one picture cannot
   tell it from a pawn standing on e3 (all 5 v1 mid-move errors were such centred passes). v2 names a piece only
   if the previous picture's best match on that square was the same kind (reason `unconfirmed` otherwise).
   `read(image, corners, cal, previous=...)` takes the previous reading; without one nothing is named. Cost: a
   piece that just arrived is "unsure" for one picture.
4. **Picture quality.** From the rectified board, every internal light/dark boundary is cut into 8 segments; rows
   crossed by a piece are dropped, and the rest give a blur width and an offset from where the corners put the
   boundary. A picture is `poor-picture` (every square unsure) when the blur in the worse direction exceeds 1.7
   board pixels (detail lost relative to a square: tiny boards, motion blur), or 4.5 camera pixels (focus), or the
   90th-percentile boundary offset exceeds 2.0 board pixels (lens bow, wrong corners), or fewer than 16 of 112
   segments are measurable. **Correction to the v1 text above:** 2 % lens bow is not "safe, but useless"; the
   review found confident errors there. v2 refuses any picture whose boundaries are bent by more than 2 board
   pixels, which covers 1 % bow and more on the tuning pictures.
5. **Guard output.** `compare(result, believed)` returns per square `consistent` (the reader names the believed
   piece), `objection` (it confidently names something else, including a piece on a square believed empty) or
   `cannot-tell`, and one verdict: `objection` if any square objects, `consistent` if every believed piece is
   confirmed, else `cannot-tell`. Agreement is never proof. Because kings and queens are never named, the verdict
   on a full position is at best `cannot-tell`; only objections carry information.

Runtime inputs only: pictures, corners, the reviewed start position, the previous reading and, for `compare`,
the believed position. Truth is read only by `evaluate` and the attack scripts, for scoring.

**Tuning.** Start limits were fitted on the 14 smoke + dev starts and 66 own-seed start pictures (seeds
51001-51066: 30 clean ones in three styles with coordinates, themes, medium and hard cameras; 36 with an arrow,
glare, move dots or a highlight). On those 80: clean starts refused 0 of 44 (14 scene + 30 own), arrow starts
12 of 12, glare 10 of 12, dot starts 6 of 6, highlight under a piece 2 of 6. Quality limits were fitted on the
445 smoke + dev pictures and 128 own-seed damaged pictures (seeds 61001-61032). A tried 5 % tolerance band at
the gain limits was dropped: on dev it blocked 719 squares, all correct (blurred pictures fit real pieces just
above the 0.6 floor). The other v1 constants are unchanged; `MARGIN_THIN` 3.0 and `EVIDENCE_MIN` 2 were set by
reasoning, not tuned.

## v2 results on the report splits (frozen v2 sha256 `c19efcf5...35b61`; run once; true corners; occupied squares)
| split | v1 correct / wrong / unsure | v2 correct / wrong / unsure | v2 unsure without kings and queens |
|---|---|---|---|
| smoke2 | 1,344 / 0 / 0 of 1,344 (0 %) | 1,163 / 0 / 181 of 1,344 (13.5 %) | 13 of 1,176 |
| dev2 | 25,619 / 0 / 2,638 of 28,257 (9.3 %) | 20,247 / 0 / 8,010 of 28,257 (28.3 %) | 4,191 of 24,438 |
| stressdev | 40,245 / 0 / 1,836 of 42,081 (4.4 %) | 30,726 / 0 / 11,355 of 42,081 (27.0 %) | 5,976 of 36,702 |

Empty squares named as a piece by v2: 0 of 1,344, 0 of 36,447, 0 of 44,511. Mid-move pictures (v1's evaluation
skipped them; v2 scores them): stressdev 768 squares, 311 named, all as the piece standing there before or after
the move, **0 confident-wrong**.

Why v2 is unsure (occupied squares): dev2 thin evidence (kings and queens) 3,500, poor picture 2,119, small margin
762, thin runner-up 759, poor fit 540, unconfirmed 327; stressdev thin evidence 4,603, no reference 3,636 (3
refused starts), poor picture 2,168, unconfirmed 362, thin runner-up 302, small margin 248. On stressdev the lens
games are refused almost entirely (3,607 of 3,633 unsure: two starts refused, the rest poor picture), and one of
the three theme-colour games had its start refused (2,371 of 3,405 unsure).

**Cost of v2** (unsure share and refusals):
| measure | v1 | v2 |
|---|---|---|
| unsure, smoke2 / dev2 / stressdev | 0 % / 9.3 % / 4.4 % | 13.5 % / 28.3 % / 27.0 % |
| clean scene starts wrongly refused (smoke, dev, smoke2, dev2, stressdev) | 0 of 64 | 3 of 64 (stressdev: 2 lens-distortion, 1 theme-colours) |
| clean mid-game starts refused, reviewer scripts (reduced material) | 0 of 84 | 6 of 84 (2 of 36 easy-medium-hard, 4 of 48 hard) |
| clean starts refused, reviewer start-dirty script | 0 of 6 | 0 of 6 |
| false alarms on unchanged pictures (verdict objection) | 0 of 126 / 3,033 / 4,059 pairs | 0 of 42 / 1,011 / 1,353 pictures |

## Guard use: constructed swaps and substitutions (claim = the old position)
Each changed picture is read as a settled scene (previous reading = the same picture), as it would be from the
second picture after a real change. Noticed = objection on a changed square; missed = both changed squares
confidently read as the claim; cannot tell = otherwise.
| split | v1 swaps noticed / missed / unsure | v2 swaps | v1 substitutions | v2 substitutions |
|---|---|---|---|---|
| smoke2 | 126 / 0 / 0 of 126 | 126 / 0 / 0 of 126 | 126 / 0 / 0 | 101 / 0 / 25 |
| dev2 | 2,900 / 0 / 133 of 3,033 | 2,616 / 0 / 417 of 3,033 | 2,738 / 0 / 295 | 2,065 / 0 / 968 |
| stressdev | 3,978 / 0 / 81 of 4,059 | 3,454 / 0 / 605 of 4,059 | 3,892 / 0 / 167 | 2,890 / 0 / 1,169 |

## Reviewer attack scripts, v1 against v2 (original seeds, not tuned on)
The reviewer's scripts (`/Users/alexmunzon/chess-builds/review-piece-reader-2026-11-16/`) were copied to `atk/` and
run unchanged through `atk/run_v2.py`, which installs v2 under the name the scripts import. Two adapters: a start
v2 refuses counts as "START REFUSED" where a script counts that, and a picture read without a previous reading
is read as a settled scene (previous = the same picture), so the confirmation rule is neutral and the other rules
are measured on their own. Only `atk_transition.py` part 1 was changed: it now reads every picture of the game in
order and passes the previous reading, which is how the confirmation rule is meant to run. v1 numbers are the
reviewer's logs. Squares tried = occupied + empty squares read; confident-wrong = wrong kind named + empty square
named as a piece. Each v2 result was looked at once, after the run; nothing was changed afterwards.
| attack family (script) | v1 tried / confident-wrong | v2 tried / confident-wrong | v2 starts refused |
|---|---|---|---|
| 1 clean mid-game start, reduced material (`atk_midgame_clean`) | 13,824 / 4 | 13,056 / 0 | 2 of 36 (clean) |
| 1 same, hard conditions (`atk_midgame_hard`) | 18,432 / 8 | 16,896 / 0 | 4 of 48 (clean) |
| 2 dirty start: arrow, glare, hand, highlight (`atk_start_dirty`) | 39,168 / 50 | 25,728 / 0 | arrow 12 of 12, glare 11 of 12, hand 12 of 12, highlight 0 of 60, clean 0 of 6 |
| 3 kind never shown, builder's dev2 pictures (`atk_missing_kind_existing dev2`) | 6,689 / 81 | 6,689 / 0 | 0 of 12 |
| 3 same, stressdev pictures (`... stressdev`) | 10,292 / 3 | 10,292 / 0 | 3 of 36 (same 3 as the stressdev run) |
| 3 kind never shown, fresh renders (`atk_missing_kind`) | 7,680 / 0 | 7,680 / 0 | 0 of 60 |
| 4 mid-move pictures, stressdev (`atk_transition` part 1) | 768 / 5 | 768 / 0 | |
| 4 capture in progress (`atk_transition` part 2) | 6,144 / 0 | 6,144 / 0 | |
| 5 heavy picture damage (`atk_degrade`) | 52,992 / 44 | 43,776 / 0 | 24 of 138, all in the lens-bow, 18-24 px motion-blur and 6-8 % board settings |
| shifted and real-finder corners (`atk_corners`) | 304,384 / 14 | 304,384 / 0; with the real corner finder dev2 6,842 of 9,419 occupied named, all correct | 99 of 224 (starts read with the same shifted corners; the scene starts themselves are clean) |
| overlays, cursor, rings, highlights (`atk_overlays`) | 16,128 / 0 | 16,128 / 0 | 0 of 6 |
| fresh swaps and substitutions (`atk_fresh_swaps`) | 27,648 / 0 | 27,648 / 0; swaps noticed / missed / cannot tell 725 / 0 / 139 of 864 (v1 797 / 0 / 67), substitutions 435 / 0 / 429 of 864 (v1 699 / 0 / 165) | 0 of 36 |
| style change, board flip (`atk_theme_flip`) | 30,720 / 0 | 30,720 / 0; stale-orientation flip noticed 36 of 36 (v1 36 of 36) | 17 of 128 (clean starts) |

At the damage levels the review listed, v2 made no confident error, but it does not answer "cannot tell"
everywhere: blur sigma 4 still named 26 of 1,152 occupied squares (all correctly) and a 6 % board 102 of 960
(all correctly); 24 px motion blur and 2-3 % lens bow give "cannot tell" or a refused start everywhere.

## Tests and mutants
`python3 -B tests/piece_classifier_v2.py`: 22 tests, about 10-15 s. `mutation_v2.py` (output folder) removes or loosens
each rule in a private copy and runs the tests against it. All seven rules the brief names are caught: fit gate
removed (fails `test_poor_fit_with_clear_margin_is_unsure`), gain gate removed
(`test_over_bright_piece_needing_gain_above_ceiling_is_unsure`), gain floor 0.6 -> -3.0
(`test_colour_inverted_piece_is_not_named_as_itself`), margin 2.0 -> 1.5 (`test_margin_between_1_5_and_2_is_unsure`),
start-cleanliness check removed (3 start tests), thin-evidence rule removed (6 tests, among them
`test_kind_learned_from_one_square_is_never_named`), mid-move confirmation removed
(`test_piece_passing_over_a_square_is_not_named`). Also caught: missing-kind gate, picture-quality gate, the
empty-square and sibling start checks separately, the no-piece-seen gate. Not caught (2 of 14): removing the
outside-image gate (other gates still stop those squares in the test) and loosening the thin runner-up margin
3.0 -> 2.0. Log: `logs/mutation_v2.log`, 12 of 14 caught.

## What still fools it or is not covered
- **Kings and queens are never named** in a game that starts from the standard position (one start square each).
  A swap involving a king or queen is "cannot tell", never an objection. Learning a second example (for example
  the first reviewed picture after the queen has moved) would lift this.
- **A dirty start that slips through**: 1 of 12 glare starts in the reviewer's script and 2 of 12 in the tuning
  set were accepted. With an accepted dirty start the rules that remain are the margins and the thin-evidence
  rule; no confident error came from these starts in the runs above, but the protection is thinner.
- **Kinds with one start square** cannot be checked for dirt at all (no siblings), so a glare spot on a lone queen
  at the start makes the queen template wrong. The queen is never named, but its distorted shape still acts as a
  runner-up for other kinds, where the 3.0 thin margin is the only guard.
- **A missing kind blocks its whole colour.** A reviewed mid-game start without, say, a white bishop makes every
  white piece "cannot tell" for the whole game.
- **The confirmation rule needs a real picture sequence.** A piece held still mid-move for two pictures (a slow drag
  that pauses exactly on a square) would be named. The simulated mid-move pictures are single frames.
- **Highlights under pieces are learned into the shapes** (0 of 60 highlight starts refused). No error came from it,
  but those shapes include the tint.
- **The quality limits are fitted on the simulator's own blur, noise and lens models**; a real camera's
  defocus, rolling shutter and screen moire were not measured.
- **Clean starts refused**: 3 of 64 scene starts and 6 of 84 reviewer mid-game starts; each forces a re-review.
- **Low-contrast board colours are mostly unreadable.** In the reviewer's theme script v2 named nothing for 8 of
  12 "same look" settings (gray, green, night and pale boards) and refused 17 of 128 clean starts. One probe
  (seed 97000, classic pieces on the gray board) shows why: the start is accepted, but the boundary-offset
  measure is noisy when light and dark squares differ by only about 19 grey levels (misalignment 2.45 against
  the 2.0 limit), so every picture counts as poor. Safe, but a real cost; scaling that limit to the measured
  noise is the likely fix (not done: it would need every measurement re-run).

## What it would take to use v2 as a guard
1. Feed it from the pipeline, not from truth: detected corners plus the pipeline's orientation lock, and the
   reviewed start from the app's start review. Measure once on held-out data scored by the orchestrator.
2. Wire it so it can only withhold: an `objection` verdict pauses advice and asks for review; `cannot-tell` and
   `consistent` change nothing; it never moves the tracked position.
3. Run it on every settled picture and pass the previous reading (the confirmation rule depends on it).
4. Decide the king and queen gap: either accept that king/queen swaps are invisible to the guard, or add learning
   from a later reviewed picture.
5. Port to Swift and time it on the phone (Python: rectify + quality median 108-209 ms, reading median 67-74 ms
   per picture on a loaded Mac).
6. Real screen and camera footage; everything above is simulated.

All v2 results: simulated pictures, on a Mac, true corners unless stated, not camera evidence.

# Review of v2 and the withhold-only guard (2026-11-17, simulated images only)

**Review result.** An independent review (scripts and logs: `/Users/alexmunzon/chess-builds/review-piece-reader-v2-2026-11-17/`)
found v2 **usable only as a guard that can withhold advice**, with four conditions: act only on `objection`; treat
`consistent` as no information; always pass the full believed position; a crash must withhold advice. Why
`consistent` cannot be trusted: a start reviewed wrongly in a self-consistent way (knight and bishop swapped on both
sides, rook and knight swapped, board turned 180 degrees) is learned without complaint, and `compare` then calls the
wrong squares consistent (`demo_guard.py`: 8 of 8); a piece paused mid-slide was named on 43 of 43,885 named squares
(`atk_c_midmove.py`) and reads consistent if the tracker made the same mistake. The review also found 12 of 43
malformed inputs crashing (`atk_f_robust.py`), a partial believed position able to give `consistent`, and 10 of 20
mutants surviving the tests (`mutate.py`).

## Changes to the reader (2026-11-17; each can only remove a name, an objection-free "consistent", or a start)
Reading thresholds are unchanged, so the v2 numbers above stay valid. sha256 of `piece_classifier_v2.py` after
round 1: `1e04c76e...7974a622e`; after round 2 (below): see "Round 2". v1 is unchanged (`e5c31e2e...44523`).
1. **No public function raises on bad input.** `calibrate` refuses a start it cannot use (empty list, board outside
   the picture, unreadable FEN, a start with no pieces, start pictures with different orientations, NaN or infinite
   pixels, any internal error): state `no-reference`, problem `unusable-start` (v1 and v2 raised `CalibrationError`).
   `read` answers `unsure` on every square with reason `no-reference` (no start, refused start, a start dict without
   a state), `bad-corners`, `bad-image` (grayscale or RGBA arrays, non-RGB PIL pictures, empty arrays, NaN or
   infinite values anywhere), `orientation-changed` or `read-failed` (any exception inside the reader).
2. **Orientation must match the start.** The start records the board's screen orientation; a later picture whose
   corners put a8 elsewhere on screen is `orientation-changed` everywhere. This removes the review's only confident
   error in `atk_f_robust.py` (corners turned by two: 28 wrong names). A board flipped on screen mid-game is now
   refused until a new start is reviewed (a cost). Since round 2 `evaluate` applies the same refusal (it calls the
   inner reading step directly; turned pictures get no constructed swaps either); no non-held-out scene game changes
   orientation (0 of 1,544 frames). `read_tiles` and `_settled` themselves still do not check orientation: only
   `read()` and `evaluate` do.
3. **`compare` cannot say `consistent` on a partial or malformed position.** A malformed reading, or a belief that
   is not a dict, gives `cannot-tell` everywhere; a malformed belief entry (key off the board, value not a piece
   letter) makes its own square `cannot-tell` and the overall answer `cannot-tell` (`malformed-belief`) unless another
   square objects (round 2: an objection is kept); a refused reading, a belief without exactly one king of each colour (`partial-belief`),
   or a square believed empty that the reader did not see as clearly empty gives `cannot-tell` overall; an objection
   is kept. `compare` now also returns a `reason`.

## The guard: `scripts/recognition/piece_guard.py` (as of round 7)
**The one caller pattern:** `if out.must_withhold(): pause advice` (reasons in `out.reasons`), read at once;
otherwise change nothing. `no objection` is no information and must never restore or grant advice.

`PieceGuard(start_pictures, start_fen, withhold_on_unsure_disturbed=True)`, then per settled picture either
`check(image, corners, believed, disturbed=())` or `check_after_move(image, corners, believed_before, believed_after)`;
`rebaseline_after_human_review(image, corners, reviewed_position)` is the third, rare call (see Baseline). All return a `GuardOutcome` with two possible
values: withhold (always with at least one reason) and no objection. `must_withhold()` returns a plain bool and is
False only for a genuine no-objection outcome made by the guard itself **when no later call on the same guard has
started**: every call takes a sequence number when it starts, so a "no objection" kept and read after a later call
began reads as withhold (also when an older call finishes after a newer one started), and one a caller builds by hand
always counts as withhold. Calls on one guard are serialised by a lock, so two threads cannot interleave a reading
and a baseline update. A call made on a guard from inside another call on the same guard in the same thread (for
example from a hook in the reader) does not wait for the lock, which would hang the guard for good: it returns at once
a withhold with the reason `re-entrant-call: ...`, without reading the picture or moving the baseline, and since it took
a sequence number, the outer call's answer reads as withhold too. **Known gap:** this check sees only the same
thread. A hook that hands a call on the same guard to another thread and waits for it blocks until the hook stops
waiting (forever if it waits without a time limit), because the other thread waits for the lock the first call holds.
`out == WITHHOLD` and `out == NO_OBJECTION` follow
`must_withhold()`. Everything else raises `TypeError`: other comparisons, ordering, hashing, `if out:`, `str(out)`,
f-strings and `%s`, the old `.outcome` attribute, any unknown attribute (so `getattr(out, name, default)` raises too),
pickling and copying. `repr(out)` is kept for logs and never equals either constant.

It withholds on any objection; any exception other than interrupt-type ones (KeyboardInterrupt, SystemExit) from the
reader, from validating the caller's input (including hostile string subclasses) or inside the guard; a missing or
refused start; a refused or malformed reading or `compare` answer; a believed position that is not a plain dict of
board squares to piece letters, or is impossible (not exactly one king of each colour, a pawn on rank 1 or 8, more
than 8 pawns or 16 pieces of one colour); square lists that are not a square name, None, or a tuple, list or set of
square names; and "cannot tell" on the squares the calling style names. Every input is validated and copied once at
entry (strings copied as plain strings, without calling a subclass's methods) and only the copies are used
afterwards. The previous reading is dropped before every read. The strict setting is read-only after creation, and
only the value `False` itself turns it off.

**`check_after_move` checks the shape of one real move, nothing else.** Accepted, and only these: (i) one piece leaves
one square and the same piece (colour and kind) arrives on a square that was empty or held an enemy piece other than
a king, along a line its kind can move on an empty board (knight L, bishop diagonal, rook straight line; pawn one
forward to an empty square, two forward from its start rank to an empty square, or one diagonally forward onto an
enemy piece); (ii) promotion: a pawn leaves the 7th rank (white) or 2nd rank (black) and a rook, bishop or knight of
its colour arrives on the last rank, straight onto an empty square or diagonally onto an enemy piece (a queen
promotion withholds, see below); (iii) en passant: a pawn moves diagonally onto an empty square of the 6th (white) or
3rd (black) rank and the enemy pawn beside its origin square is removed. Everything else withholds: castling, two
movers, a piece vanishing or appearing, in-place kind or colour changes, teleports, identical positions, any move
that vacates a king or queen square and any arriving king or queen (the reader never names them). **Move legality is
the tracker's job**: blockers, checks and whose turn it is are not checked. "Cannot tell" on the arrival square
withholds whatever the strict setting; vacated squares withhold only on an objection.

**Baseline.** The guard keeps the position it last accepted: the reviewed start position after construction, then
`believed_after` of each `check_after_move` that answered no objection. `believed_before` must equal the baseline or
the call withholds (`before-differs-from-baseline`). After a withhold the baseline does not move: the same move can be
checked again on the next picture (the first picture after a move cannot confirm the arrival square, so a single
withhold there is normal), but any later move withholds until the caller calls
`rebaseline_after_human_review(image, corners, reviewed_position)`, which sets the baseline to that position only when
a full check of it answers no objection **and the picture gives real evidence for it**: the reader must name,
consistently with the reviewed position, at least `REBASELINE_NAMED_SHARE` (0.75) of the pieces it is able to name
(pawns, knights, bishops and rooks of a colour whose six kinds were all learned at the start, each from at least
`EVIDENCE_MIN` start squares; never kings or queens), and at least one; and no square may be `unconfirmed` by the
reader (round 7: the previous picture showed another kind there, so the picture changed, and a changed square is
"cannot tell" and could hide a piece the reviewed position lacks). On any objection, refused reading, invalid
position, too little evidence (`too-little-evidence: n of m nameable pieces named`) or an unconfirmed square
(`unconfirmed square (picture changed since the previous one): g5`) it withholds and leaves the baseline unchanged.
Call it on a picture the guard has just seen (a settled picture seen twice). **Known gap:** a position whose only
pieces are kings and queens has 0 nameable pieces, so it can never be re-baselined (every attempt withholds). Without that rule a picture that shows nothing (degenerate corners, even collinear ones, make the
reader say "cannot tell" on all 64 squares without refusing) gave no objection and moved the baseline to any valid
position. The first picture of a new guard always names nothing (no previous reading to confirm against), so a
re-baseline needs a picture the guard has already seen once; on the 50 honest re-baselines of the legal-play run the
reader named 100 % of the nameable pieces each time (round 6). `check_after_move` needs no such rule: it already
withholds unless the reader names the arrival square. **When a move moves the baseline:** at the moment its no
objection is decided, inside the call, and only if no later call on the guard has started by then (checked under the
same lock that hands out sequence numbers). If a later call starts after that moment, the caller reads withhold (the
answer is stale) although the baseline has already moved to `believed_after`. That fails safe: `believed_after` was
checked with no objection on that picture; repeating the same move then withholds (`before-differs-from-baseline`)
until a re-baseline after human review, and a next move from `believed_after` is checked as usual, so the stale case
can only add withholds. Moving the baseline on a withhold would let a move the guard could not check (for example a
queen move that never happened) silently become the base for every later check.
**Call `rebaseline_after_human_review` only after a person has reviewed the full position. Calling it automatically
after a withhold defeats the guard.** The guard cannot see wrong kings or queens, or pieces invented on empty squares
(the reader never names kings or queens and never says "empty"), so an unreviewed position with such errors is
accepted. The review's case is pinned down in `test_automatic_rebaseline_after_a_withhold_is_the_documented_limit`:
the knight really moved and the tracker also believes the queen vanished; the move withholds, an automatic
re-baseline on the same picture is accepted, and the next move gets no objection. The old `check(..., rebaseline=True)`
was removed; passing `rebaseline` now raises `TypeError`.

**The first picture after every move withholds; the second accepts.** The reader names a piece only when the previous
picture's best match on that square was the same kind (its mid-move rule, rule 3 of v2), and the previous picture
showed the old position, so the arrival square is "cannot tell" on the first picture after a move; this is the rule
working as designed (it stops a piece caught mid-slide from being named).

**Ways to call it** (123 honest moves in 4 rendered games, clean pictures; `cost_moves3.py`, round-4 copy, in which
the caller re-baselines on the same picture after each withheld move, which SIMULATES a human review that was not
done; see round 5 for the legal-play cost). Game 1 is a real game (the Opera game); games
2-4 are random own-piece moves to random squares, which are not real moves:
| calling style | withholds on honest moves |
|---|---|
| 1. `check(..., disturbed=from and to squares)`, strict default: "cannot tell" on any listed square withholds | 123 of 123 (the reader never says "empty", so the vacated square is always "cannot tell") |
| 2. `check(...)` with `withhold_on_unsure_disturbed=False`: only objections and failures withhold | 0 of 123 |
| 3. `check_after_move(..., believed_before, believed_after)` | real game: ordinary 0 of 16, captures 0 of 11, king or queen 5 of 5, castling 1 of 1; random games: 83 of 90, because 69 of their 76 non-king, non-queen "moves" are not moves any piece can make (every rejection checked by hand) and 14 are king or queen moves; all 4 games: ordinary 49 of 70, captures 20 of 33, king or queen 19 of 19, castling 1 of 1, total 89 of 123 |

The default of `check` stays style 1 until the owner decides.

**The guard is not connected to anything**: not to the screen pipeline, the move tracker, the app or
`scripts/check-all.sh`. Tests: `python3 -B tests/piece_guard.py`.

## Checks after the change (2026-11-17)
- `python3 -B tests/piece_classifier_v2.py`: 30 of 30 passed (22 before; `test_bad_inputs_are_refused` now expects a
  refusal answer instead of an exception; 8 tests added). `python3 -B tests/piece_guard.py`: 7 of 7 passed. Against
  the old module, 4 of the v2 tests and 3 of the guard tests fail, as they should.
- Mutation check (the reviewer's `mutate.py`, copy in `/Users/alexmunzon/chess-builds/piece-guard-2026-11-17/`):
  20 of 20 caught (10 of 20 in the review). The 10 new catches come from 8 added tests; one mutant (thin runner-ups
  judged like well-learned kinds) never changes a label, only the reason (`small-margin` instead of `thin-runner-up`)
  and the reported `marginSolid`, so it is caught on the reason, not on a wrong name.
- `atk_f_robust.py`: 0 crashes of 43 (12 in the review), 0 confident-wrong names (28 in the review, all from corners
  turned by two).
- `atk_d_compare.py`: changed square reported consistent 0 of 3,104 and verdict consistent on a wrong belief 0 of
  3,104, as in the review; every family count is identical.
- `atk_a_start.py`: unchanged from the review (accepted doctored starts 12 of 23; accepted starts that later named
  something wrongly 3 of 23). A self-consistently wrong start is still accepted; the guard gives at most
  `no objection` there.
- smoke2 evaluation: unsure 181 of 1,344 occupied squares before and after, wrong 0, every other count identical.

## Round 2 (2026-11-17): the guard review's conditions
A second independent review (`/Users/alexmunzon/chess-builds/review-piece-guard-2026-11-17/`) accepted the guard with
conditions. What changed (outputs and logs: `/Users/alexmunzon/chess-builds/piece-guard-2026-11-17/round2/`):
- **Equality trap closed.** `out == WITHHOLD` was always False, even for a real withhold. Now equality with the two
  outcome constants answers correctly, and any other comparison raises. This was chosen over "every comparison
  raises": the natural careless line `if out == WITHHOLD:` now withholds instead of crashing in caller code that may
  swallow the error, and a misspelled constant still raises instead of quietly reading as "no withhold".
- **Impossible believed positions withhold** (pawn on rank 1 or 8, more than 8 pawns or 16 pieces of a colour, not one
  king each, squares off the board, unknown letters). **Every withhold has a reason** (enforced when an outcome is made).
- **Misuse cases withhold**: the believed position and square lists are copied once at entry; a dict subclass with a
  lying `get()`, a falsy object that yields squares, generators (reused or not), odd `compare` answers and changing the
  strict setting after creation all withhold or raise `AttributeError`. The previous reading is dropped before every read.
- **`compare` keeps an objection** when the believed position also has a malformed entry elsewhere (was 21 of 21 lost).
- **A start passed as a one-pass iterator** was already turned into a list by `calibrate` in round 1 (`list(...)`, one
  line); left as is.
- **`evaluate` refuses a turned board** like `read()` (smoke2 unsure 181 of 1,344 before and after).
- **`check_move(arrived, vacated)`** added as the third calling style; replaced in round 3 by `check_after_move`.
- sha256: `piece_classifier_v2.py` `07632cb071543415dfcf230d770b423b94dd0bc9befcd9991ca91bc63a13726f`,
  `piece_guard.py` `832fd74fd94bd7cb89b3c1a95e1463a490b879e88eb603192fcf1a6f184fcc31`; v1 unchanged.

Checks after round 2: `tests/piece_classifier_v2.py` 30 of 30; `tests/piece_guard.py` 15 of 15; `tests/piece_classifier_v1.py`
11 of 11. Guard mutants (the review's 24, patterns moved to the new code): 23 of 24 caught. The survivor ("unexpected
verdict accepted") cannot change behaviour: the guard rejects any `compare` answer whose verdict is not objection,
consistent or cannot-tell before that line, and objection returns earlier, so the line is unreachable. Reader mutants
20 of 20. The review's `atk_guard.py` (copy with three probes wrapped because they now raise): dangerous outcomes belief
0 of 48, disturbed 0 of 22, exception 0 of 18, odd reader 0 of 9 (all deliberately faked readers), state 0 of 4;
`atk_guard_followup.py`: a reused generator withholds on both calls and `out == WITHHOLD` is True on a real withhold.
`atk_f_robust.py` 0 crashes of 43, 0 confident-wrong; `atk_d_compare.py` consistent on a wrong belief 0 of 3,104 (all
family counts as in the first review). Exceptions that are not `Exception` (KeyboardInterrupt, SystemExit) still pass
through the guard on purpose; the previous reading is cleared before the read, so nothing stale is kept.

## Round 3 (2026-11-17): the second guard review's conditions
A second review of the guard (`/Users/alexmunzon/chess-builds/review-piece-guard-round2-2026-11-17/`) found that
`check_move` trusted the caller's square lists (4 of 8 "unlisted" cases gave no objection while the real arrival
square was "cannot tell"), that 12 natural ways of reading an outcome missed a withhold without an error, that the
belief was read again after the picture, and 5 surviving mutants. Changes (outputs: `.../piece-guard-2026-11-17/round3/`):
- `check_move` removed; `check_after_move(before, after)` derives the changed squares itself (section above).
- The outcome is read with `must_withhold()`; `.outcome`, `str()`, format, unknown attributes, pickling and copying
  raise; a hand-built no-objection counts as withhold.
- Only the entry copies are used after the read (`test_entry_copies_are_used_after_the_read`; it fails when the guard
  re-reads the caller's belief).
- `_withhold`'s fallback reason was unreachable and is removed; an empty withhold now raises inside the guard and is
  caught as a guard error, which still withholds.
- New tests: black-king count, 8 pawns and 16 pieces allowed and 9 pawns (with 16 pieces) and 17 pieces refused for
  each colour, the move shapes (identical, no arrival, 3 arrivals, 4 changed squares, castling), en passant and
  promotion, and the outcome-reading rules.
- The reader file did not change in round 3 (sha256 `07632cb0...a13726f`). `piece_guard.py` sha256:
  `fc8fec6d57f95de7d58a929fcd7987a955fc9c1461e0989b7b177d1d8abef3b3`. v1 unchanged.

**Ways of reading an outcome that still miss a withhold** (`atk_equality.py`: 5 of 56 expressions, down from 12).
Python does not let an object intercept these, so they stay wrong; use `out.must_withhold()`:
`out is WITHHOLD`, `out is None` (as a withhold test), `isinstance(out, str) and out == WITHHOLD`, `match out: case
str()`, and `repr(out) == WITHHOLD` (`repr` is kept readable for logs; it never equals either constant).

Checks after round 3 (all run on 2026-11-17): `tests/piece_classifier_v2.py` 30 of 30; `tests/piece_guard.py` 20 of
20; `tests/piece_classifier_v1.py` 11 of 11. The second review's 28 mutants (patterns moved to the new code; the
`check_move` mutants mapped to the nearest rule of `check_after_move`): 28 of 28 caught. `atk_check_move.py` adapted to
`check_after_move` with every case kept: dangerous wrong-arrival 0 of 5, cannot-tell-arrival 0 of 4, unlisted 0 of 8,
lists 0 of 11, special 0 of 10, vacated-occupied 0 of 4; a belief corrected during the read is judged in its entry
version (withhold, objections f3 and c4) for both calls. The first review's `atk_guard.py` unchanged through
`run_original_stepwise.py`: every case that reads `.outcome` now raises (by design), so the copy with `rec()` reading
`must_withhold()` was also run: dangerous belief 0 of 48, disturbed 0 of 22, exception 0 of 18, odd reader 0 of 9 (all
deliberately faked readers), state 0 of 4.

## Round 4 (2026-11-17): the third guard review rejected `check_after_move`; fixed
The third review (`/Users/alexmunzon/chess-builds/review-piece-guard-round3-2026-11-17/`) found 6 dangerous answers of
79: changes counted but never checked as a real move (a knight move while a queen vanished passed), `believed_before`
never compared with what the guard last accepted, in-place kind changes and teleports accepted (the round-3 text above
overclaimed: "accepted shapes" meant only square counts), no tie between an outcome and its call, a hostile string
subclass making an exception escape, and 2 surviving mutants. Changes (outputs: `.../piece-guard-2026-11-17/round4/`):
real single-move shapes only, the baseline, sequence-numbered outcomes, plain-string copies of all input with every
validation failure withheld (section "The guard" above). The reader file did not change (sha256 `07632cb0...a13726f`).
`piece_guard.py` sha256: `05375075babdeda70c4c206bc8974704a805261466a36fc0f77d421b47d35ad9`. v1 unchanged.

Checks after round 4 (all run on 2026-11-17): `tests/piece_guard.py` 23 of 23; `tests/piece_classifier_v2.py` 30 of 30;
`tests/piece_classifier_v1.py` 11 of 11. The review's `atk_after_move3.py` (copy whose seeding `check` also sets the
baseline; every case kept): dangerous 0 of 79 (illegal-shape 0 of 15, before-mismatch 0 of 5). `item3_item4.py`
(copy): in-place kind and colour changes withhold 5 of 5; a kept "no objection" reads as withhold after a later call.
The first review's 101 attacks read with `must_withhold()`: dangerous 0 of 101. Mutants: the third review's 14 moved to
the new code plus 10 for the round-4 rules, 23 of 24 caught; the earlier 28, 27 of 28 caught. Both survivors cannot
change behaviour: "before not validated" (`m10`) because `believed_before` must equal the already validated baseline,
so any accepted before is itself valid; "must_withhold ignores genuineness" (`r24`) because only genuine outcomes ever
carry an issuer and sequence number, which must_withhold also requires. The third review's `m12` (only the first
arrival checked) no longer applies: every accepted shape has exactly one arrival.

## Round 5 (2026-11-17): the fourth guard review's conditions
The fourth review (`/Users/alexmunzon/chess-builds/review-piece-guard-round4-2026-11-17/`) accepted round 4 with
conditions: automatic re-baselining after a withhold brings back the round-3 failure, the sequence number was read when
a call ended (so an older call finishing after a newer one read as valid), the claim that mutant m10 could not change
behaviour was wrong (a string subclass passed as `believed_before` hid a vanished queen; the code already copied it,
but no test showed it), and 9 behaviour-changing mutants were not caught by the tests. Changes (outputs:
`.../piece-guard-2026-11-17/round5/`): `check(..., rebaseline=True)` replaced by `rebaseline_after_human_review`
(section above; the old parameter raises `TypeError`); sequence numbers taken when a call starts, calls serialised by a
lock; tests for each of the 9 mutants, the string-subclass "before", two threads and the automatic re-baseline limit.
Every script of this work that re-baselined automatically now says in its output that it simulates a human review.
The reader file did not change (sha256 `07632cb0...a13726f`). `piece_guard.py` sha256:
`5c3f49d6200b1b04bb79e0a3ef65f4a0ea77d81dd4c7af842d681b71c369881c`. v1 unchanged.

Checks after round 5 (all run on 2026-11-17): `tests/piece_guard.py` 27 of 27; `tests/piece_classifier_v2.py` 30 of 30;
`tests/piece_classifier_v1.py` 11 of 11. The review's 26 mutants (patterns of six moved to the new code, same
mutation): 23 of 26 caught by the project tests; the survivors are k07 (promotion from any rank), k14 (king capturable)
and k26 (genuineness ignored), which the review already judged unable to change behaviour. `atk4.py` and `atk4b.py`
(copies, re-baseline call renamed, every case kept): 0 dangerous in every family; the thread case "A move1 vs B plain
check" now gives A = withhold (stale) and the baseline stays put. `auto_rebase.py` (copy; the documented limit, not a
pass/fail): the move withholds, the simulated re-baseline is accepted, the next move gets no objection.
Cost on legal play (`cost_legal.py` copy, 8 games, 320 moves, re-baselines simulate a human review): ordinary piece
moves 0 of 84, pawn moves 0 of 105, piece captures 0 of 47, pawn captures 0 of 24, en passant 0 of 6, under-promotion
0 of 4; king 21 of 21, queen 20 of 20, castling 7 of 7, queen promotion 2 of 2; the first picture after a move
withholds 320 of 320, as explained above.

## Round 6 (2026-11-17): the fifth guard review's conditions
The fifth review (`/Users/alexmunzon/chess-builds/review-piece-guard-round5-2026-11-17/`) accepted round 5 with
conditions. Changes (outputs, mutant copies and logs: `.../piece-guard-2026-11-17/round6/`):
- **A re-baseline needs evidence in the picture** (section "The guard", Baseline). Degenerate corners made the reader
  say "cannot tell" on all 64 squares without refusing, and a re-baseline to a wrong position was accepted
  (`badcorners.py`). Now it needs at least 0.75 of the nameable pieces of the reviewed position named consistently,
  and at least one. The share comes from the 50 honest re-baselines of the legal-play run (`measure.py`): every one
  named 100 % of its nameable pieces (at least 15 pieces each), so 0.75 keeps all 50 and still asks for a clear
  majority. These are clean rendered pictures; real camera pictures may name fewer, and a re-baseline that then
  withholds only costs advice. `check_after_move` already withheld there (it needs the arrival square named).
  Consequence: a re-baseline on the first picture a new guard sees always withholds; the test setups now show the
  picture once first (`review()` in the tests). Two old test setups had relied on the hole itself (a re-baseline to a
  position the picture did not show, accepted because nothing was named); they now use a picture of that position.
  Test: `test_rebaseline_needs_evidence_in_the_picture`.
- **A call from inside a call on the same guard** (same thread) used to hang the guard for good; it now returns a
  withhold (`re-entrant-call: ...`) at once and the outer call reads withhold. Test:
  `test_reentrant_call_withholds_and_does_not_deadlock`.
- **When a move moves the baseline** is now stated exactly (docstrings and section above): at the moment its no
  objection is decided, under the sequence lock, only if no later call has started; a later call starting after that
  makes the caller read withhold although the baseline moved, which can only add withholds. Option 1 (move the
  baseline only if the answer the caller reads is still valid) is not possible: validity is decided when the caller
  reads, after the call returned. Test: `test_baseline_moves_only_with_a_still_valid_decision_and_a_later_stale_answer_fails_safe`.
- Tests for the surviving mutants m03 and m06 (two new later-call variants in the thread test, one a re-baseline that
  withholds) and m09 (a string subclass that claims equality as `believed_before`).
- The reader files did not change (v2 `07632cb0...a13726f`, v1 `e5c31e2e...44523`). `piece_guard.py` sha256:
  `6426a8bbaa2f95ec20914bf7a93c4f10c5f688b708371c0f576f7a0d5dd73ea5`.

Checks after round 6 (all run on 2026-11-17): `tests/piece_guard.py` 30 of 30. The review's 17 mutants (anchors moved
to the new code, same mutations; `run_one.sh`): 15 of 17 caught, 14 by the tests and m11 by `atk5.py` only; m14 and
m15 survive, as the review judged them near-equivalent. Three extra mutants that remove each new protection (no
evidence rule, no re-entrancy check, one named piece enough) are caught by the tests, and the round-5 guard fails 3 of
the 30 tests. `badcorners.py`: every re-baseline withholds, baseline unchanged. `atk5.py`: 0 dangerous in every
family (re-entrant call: withhold, no hang). `atk4.py` 0 dangerous in every family; `atk4b.py` output identical to
round 5. `cost_legal.py`: the same table as round 5 (ordinary 0 of 84, pawn moves 0 of 105, piece captures 0 of 47,
pawn captures 0 of 24, en passant 0 of 6, under-promotion 0 of 4; king 21 of 21, queen 20 of 20, castling 7 of 7,
queen promotion 2 of 2), re-baselines 50, failed 0.

## Round 7 (2026-11-17): the sixth guard review's condition
The sixth review (`/Users/alexmunzon/chess-builds/review-piece-guard-round6-2026-11-17/`) found 5 dangerous answers of
92: after the guard saw picture X, a re-baseline claiming X on a slightly different picture Y was accepted, because the
changed square was `unconfirmed` (counted as "cannot tell") and the other pieces met the 0.75 share. Changes (outputs:
`.../piece-guard-2026-11-17/round7/`): a re-baseline now withholds when any square of its reading is `unconfirmed`
(the reader's exact reason string); the two known gaps (only kings and queens left; a hook that hands a call to
another thread and waits) are in the guard section above. Tests: `test_rebaseline_refuses_a_picture_that_changed_since_the_previous_one`
(the review's five cases), the re-entrancy test now makes each kind of inner call on its own (n12), and
`test_decision_and_baseline_update_cannot_be_split_by_a_later_call` (n17, deterministic: a later call started during
the decision must wait for the baseline update). Three test setups that re-baselined on a picture other than the one
just read now show the picture once first. Reader files unchanged; `piece_guard.py` sha256
`17cf716101392a006645b3e8e67fea08ca289de59d5ec0307d443647e19f74b6`.

Checks after round 7 (all run on 2026-11-17): `tests/piece_guard.py` 32 of 32 (the round-6 guard fails 1 of 32).
`c_follow.py`: the wrong re-baseline withholds (`unconfirmed square ...: g5`), baseline unchanged. `atk6.py` 0
dangerous of 92. The fifth review's 17 mutants: 16 of 17 caught (m11 only by `atk5.py`; m15 survives,
near-equivalent); n12 and n17 caught. `atk5.py`, `atk4.py` 0 dangerous in every family; `badcorners.py` all withhold;
`atk4b.py` identical to round 5. Cost unchanged: `cost_legal.py` table as in round 6 with re-baselines 50 of 50; the
review's `cost6.py` identical before and after (midgame 12 of 12 and endgame 5 of 7 under each condition; 5 px corner
jitter 11 of 12 and 3 of 7; the 2 endgame failures everywhere are the king-and-queen-only positions).
