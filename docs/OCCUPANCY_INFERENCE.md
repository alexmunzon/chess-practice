# Three-way occupancy move inference (prototype, 2026-11-15)

Pure logic only: no images, no camera, no classifier. Code: `src/core/occupancy-move-inference.js`.
Tests: `node --test tests/occupancy-move-inference.test.js`. Report:
`node scripts/simulation/occupancy-ambiguity-report.mjs [--games N --out file]`.

## Contract

`inferMove({ fen, occupancy }, options?)`. `fen` is a human-reviewed six-field FEN (checked by
`loadPosition`). `occupancy` is 64 entries in **a1, b1, ..., h1, a2, ..., h8** order (note:
`observation.js` lists squares from a8), each `"empty" | "white" | "black" | "unknown"`.
Hypotheses are exactly "nothing moved" plus every legal move from `fen`; it returns one of:

- `unchanged`; `move` with `move {uci, san, from, to, promotion?}` and `fenAfter` (only when one
  legal move fits); `ambiguous` with `cause` and `candidates` (several legal moves fit);
  `no-legal-explanation` (none fits: skipped plies, misread square, knocked piece);
  `uncertain` with `unknownSquares` (an unknown square could change the verdict).
- Only `unchanged` and `move` may advance the game. The other three mean "withhold and ask".
- Malformed input throws. No clock, no randomness, no history beyond `fen` plus the chosen move.

Unknown-square rule. Default (strict): any unknown gives `uncertain`, except when the known squares
already rule out every hypothesis (`no-legal-explanation`; no reading of the unknown could fix
that). Opt-in `assumeUntouchedUnknowns: true` ignores an unknown square only if no legal move from
`fen` could change it, and reports it as `assumedUnchangedSquares`. That cannot change which legal
move is picked, but it can hide a real unexplained change on that square, so it is not the default.

Speed: chess.js builds SAN for every legal move (about 1 ms per position), so the function only
tries (origin, destination) pairs the reading allows. The property test checks this pruning
against brute force (play every legal move) on 239 positions.

## Measured (seeded random games, exact occupancy)

2,000 games, up to 80 plies, seed 20261115: 159,235 plies. Unique and correct: 99.36%.
Ambiguous: 0.64% (1,013), **all** promotion piece choice; "other" ambiguity: 0. Wrong unique move:
0. Two runs gave byte-identical JSON (sha256 `81d1300e...7674`). Report:
`/Users/alexmunzon/chess-builds/occupancy-2026-11-15/run1.json` (`run2.json` is the repeat).
Why "other" is zero: a move empties its origin and fills its destination, so two different
(origin, destination) results always differ on at least 2 squares; only promotions share them.
Same reason, second experiment: one randomly misread square per ply (159,235 trials) gave
`no-legal-explanation` every time, never a wrong move. Two misreads can fool it (e4 empty + e3 white turns e2-e4 into e2-e3; not measured).
Test property run (300 games): 23,929 plies, 23,802 unique, 127 promotion-ambiguous, 0 wrong.

## What this does NOT prove

- These are random legal games with a perfect reading. No image classifier exists for this; a
  real camera will produce wrong and unknown squares, and lighting, shadows and hands will too.
- Random games are not human games (different promotion and castling rates); the percentages
  describe this sample only.
- It needs a correct reviewed starting FEN. One wrong accepted move corrupts every later move.

## How it could plug into the tracker (proposal only, nothing is wired)

`ObservationTracker.ingest` already does the same thing with 13 piece labels: it compares every
legal move's result with the reading and accepts only exactly one. A three-way mode would map
piece labels to colours (or take colour labels from a cheaper occupancy model), call
`inferMove` with the tracker's confirmed FEN, keep the existing stability, timeout and
confidence gates, and treat `ambiguous` (promotions) as a prompt: ask the user which piece.
Nothing in `observation.js`, `device-game-session.js` or the native app was changed.
