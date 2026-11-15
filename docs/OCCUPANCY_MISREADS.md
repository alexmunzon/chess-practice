# Misread squares vs occupancy move inference (2026-11-15)

Pure logic, synthetic error models, no images. Measures how wrong square readings make
`inferMove` (`src/core/occupancy-move-inference.js`, unchanged) accept a WRONG move, and four
candidate guards (implemented only as wrappers inside the report script, proposals only).
Script: `node scripts/simulation/occupancy-misread-report.mjs [--games 500 --plies 80 --seed 20261115 --trials 50 --out F]`.
Tests: `node --test tests/occupancy-misread-report.test.js` (picked up by `npm test`;
`MISREAD_BRUTE_FORCE=1` adds the slow brute-force positions). Report and repeat run:
`/Users/alexmunzon/chess-builds/pipeline-2026-11-15/misread/report.json`, `report-run2.json`
(byte-identical, sha256 `89fc6d4b...dd09c2`, about 14 min each on a loaded machine).

## Sample
500 seeded random games (same move generator and PRNG as the ambiguity report), up to 80 plies:
39,923 plies. Monte Carlo: 1,996,150 trials per error model, 3 independent frames per trial.
"Exact" numbers are the model's exact expectation over the same positions (sum over hypotheses
of P(reading equals that hypothesis)); Monte Carlo agrees within its intervals except p=0.03
label-only wrong (162 seen vs 194 expected, about 2.3 sigma; a 3M-trial single-position check agreed).

## A/B/D. Exhaustive twins (every one confirmed by calling inferMove)
- No hypothesis is ever 1 square away (0 found), matching the earlier one-misread result.
- **Two misreads**: 85.7% of plies have at least one wrong MOVE that two specific misreads make
  inferMove accept (99.96% if a wrong "unchanged" counts). Mean 2.85 wrong-move twins per ply.
  121 further twins were promotion groups (inferMove says ambiguous, not wrong).
- Patterns (all 153,836 twins): same piece, other destination 60,406; "unchanged" 39,884; a
  different piece type to the same square 29,002; same piece one or more squares short/long on
  its line 17,212; pawn single vs double push 6,261; same piece type from another origin 902;
  castling 168; en passant 1. Capture vs non-capture mismatch inside these: 19,321.
- **Three misreads**: only 0.058% of plies (38 twins: 23 en passant, 15 "unchanged").
- Misread types needed by wrong-move twins: 82% need one "empty read as piece" plus one
  "piece read as empty" (a piece seen one square off); 17% need one colour swap; 1% two swaps.
  A classifier that blurs a piece across a square edge produces exactly the common pair.

## C. Random errors, single frame, rate per ply (wrong-accepted, 95% interval)
| model | exact | Monte Carlo | correct move per frame |
|---|---|---|---|
| p=0.001 | 6.7e-7 | 0 events (rule of 3: < 1.5e-6) | 93.3% |
| p=0.003 | 5.3e-6 | 6.5e-6 [3.8e-6, 1.1e-5] | 82.1% |
| p=0.01 | 3.8e-5 | 3.4e-5 [2.6e-5, 4.3e-5] | 52.3% |
| p=0.03 | 9.7e-5 | 8.1e-5 [7.0e-5, 9.5e-5] | 14.1% |
| p=0.001, q=0.01 | 3.6e-7 | 0 (< 1.5e-6) | 49.0% |
| p=0.003, q=0.03 | 8.0e-7 | 1.0e-6 [2.7e-7, 3.7e-6] | 11.6% |
| p=0.01, q=0.1 / 0.03, 0.3 | 5.2e-8 / 1e-14 | 0 (< 1.5e-6) | 0.06% / ~0 |
Other outcomes (wrong "unchanged", no-legal-explanation, etc.) are in the JSON. Since the app re-reads after abstaining, what matters is the share of FINAL moves that are wrong:
label-only 7.2e-7, 6.5e-6, 7.3e-5, 6.8e-4 for p = 0.001 .. 0.03. At p=0.03 that is 0.055
wrong moves per 80-ply game, about one corrupted game in 18.

## Guards (label-only, re-read until accept or ask; wrong share of moves / extra cost)
- Monte Carlo saw 0 wrong events for every guard (1,996,150 trials per model, < 1.5e-6).
- G1 two-frame agreement: p=0.01 1.9e-9 (was 7.3e-5), p=0.03 1.6e-7. Cost on perfect readings:
  none abstain; one extra frame. Under noise: median frames per move 7.2 at p=0.01 (vs 1.9).
- G2 3 of 3: p=0.01 4.7e-14, p=0.03 3.9e-11; 20.7 frames per move at p=0.01, 1,040 at 0.03.
- G3 margin, literal (incl. "unchanged"): asks the human on 99.96% of PERFECT readings, since a
  normal move is always 2 squares from "unchanged". Unusable.
- G3m margin over moves only: asks the human on 85.9% of perfect readings; 9.6e-10 at p=0.01.
- G4 margin-else-two-frame: accept at once when no move twin is within 2, else need G1. 3.5e-9
  at p=0.01 with fewer frames (5.5), but UNSAFE in heavy noise (61% wrong at p=0.03, q=0.3):
  a far-away wrong move gets one-frame acceptance while the true move needs two agreeing frames.
- Redundant: "changed squares must equal the move's squares" is already implied, because
  inferMove accepts only an exact full-board match of one hypothesis.

## Recommendation
Adopt G1 (two independent readings must give the same move; G2 if frames are cheap). It costs
nothing on clean readings and cuts wrong moves by 4 to 5 orders of magnitude, at the price of
latency that grows fast with the error rate. Keep the readings independent (take the second
after the scene changes, e.g. after the hand leaves); a repeated error (shadow, glare, a piece
straddling squares) defeats G1, and only the margin rule resists that, at 86% human prompts.

## What this does NOT prove
Random legal games, not human games. Synthetic, independent, uniform per-square errors; real
classifier errors are correlated and not uniform. No camera data. Guards are not wired in.
