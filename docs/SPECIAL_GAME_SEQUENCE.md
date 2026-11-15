# Special-move synthetic image game (2026-11-15)

The bundled 14-frame replay sequence (`docs/REPLAY_SEQUENCE.md`) has no capture, castling, en
passant or promotion. `scripts/simulation/generate-special-game.mjs` renders a second, longer game
that has all of them, with the existing renderer (`render.py`, classic artwork) and one fixed clean
scene (identity panel placement, brightness 1, blur 0.1, no perspective change).

## The game (25 plies from the standard start)

1.e4 Nf6 2.e5 d5 3.exd6 (en passant) Bf5 4.dxc7 Nbd7 5.cxd8=Q+ (promotion with capture) Rxd8
6.d4 e6 7.Nc3 Be7 8.Be3 O-O (black kingside) 9.Qd2 Nb6 10.O-O-O (white queenside) Nbd5
11.Nxd5 Nxd5 12.Bd3 Bxd3 13.Qxd3. No under-promotion variant.

Output (outside the repo): `pixels/frame-000..025.png` (one PNG per position), two interruption
frames `frame-026.png` (position after 10...Nbd5 with the challenge-occlusion box, played after frame
20) and `frame-027.png` (position after 11...Nxd5 with the h2 pawn missing, played after frame 22),
`pixels/index.json` and `replay-manifest.json` in the replay-manifest schema (frames: index, file,
sha256, timestampMs; `interruption` plus an added `interruptions` list; FENs only under
`evaluatorTruth`). Expected FENs use the tracker's `forceEnpassantSquare` convention.

## Commands

```sh
B=/Users/alexmunzon/chess-builds/special-game-2026-11-15
node scripts/simulation/generate-special-game.mjs --out "$B/sequence"
SPECIAL_GAME_DIR="$B/sequence" node --test tests/special-game-sequence.test.js
swiftc -O -module-cache-path "$B/module-cache" \
  native/ChessCompanionVision/{ImageDecoder,PixelFeatures,SyntheticRecognizer,NativeVisionCLI}.swift \
  -o "$B/bin/chess-native-vision"
python3 -B native/ChessCompanionVision/conformance.py --binary "$B/bin/chess-native-vision" \
  --corpus "$B/sequence" --out "$B/native-conformance.json"
```

Without `SPECIAL_GAME_DIR` the test skips, so plain `npm test` is unaffected.

## Measured (2026-11-15, Mac)

- Two generator runs: byte-identical trees; manifest SHA-256 `9d1c5fc8…f3f6982b`.
- Test: real Python recognizer → `ReplayRuntime` JSON contract, each frame twice +100 ms, after one
  starting review. All 26 positions track to the exact expected FEN (castling rights, en-passant
  square, counters) and SAN; occlusion gives `uncertain-squares`, the missing piece gives
  `not-zero-or-one-legal-move`; good frames stay blocked until a renewed review; guidance never
  true. A copy with one corrupted expected FEN (frame 16, rights `KQk` instead of `KQ`) fails.
- Swift vs Python: 28 frames, 1792 squares, 0 disagreements, geometry agrees on all.

## Limits

Synthetic known-template images, clean scene only: not physical boards, camera, glasses or held-out
accuracy. Reviews are automated fixtures, not human reviews. Mac CPU only; no iPhone run.
