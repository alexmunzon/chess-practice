# Replay sequence for the offline "Replay game" mode

Created 2026-11-15. This prepares input for a future replay mode; it does not build that mode.

## What it produces

`scripts/simulation/select-replay-sequence.mjs` reads an existing synthetic corpus (read-only) and
picks one contiguous legal game segment (8–20 clean frames, every position seen twice so the tracker
can stabilize) plus one challenge frame as an interruption. It copies those PNGs byte-for-byte and
writes, outside the repository:

- `OUT/pixels/frame-NNN.png` and `OUT/pixels/index.json` (opaque ids, the schema the native
  conformance runner reads)
- `OUT/replay-manifest.json`: ordered frames (file, SHA-256, index, replay timestamp), the
  interruption frame, and a separate `evaluatorTruth` section with the starting FEN, expected FEN
  after each frame and the selection record. Nothing outside `evaluatorTruth` describes a position.

Ranking: most special-move kinds, then a capture, then most distinct boards, then length, then
corpus order. The 2026-11-11 corpus has no qualifying capture or special move: castling (6 frames),
en passant and promotion (4 frames each) are separate short fixtures, so the chosen segment is the
`dev-opening` game (source frames 000000–000013, 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6, 14 frames). The
interruption is the occlusion challenge frame 000068.

## Commands

```sh
CORPUS=/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/simulation-2026-11-11/corpus
OUT=/Users/alexmunzon/chess-builds/replay-sequence-2026-11-15/sequence
node scripts/simulation/select-replay-sequence.mjs --corpus "$CORPUS" --out "$OUT"
REPLAY_SEQUENCE_DIR="$OUT" node --test tests/replay-sequence.test.js
swiftc -O -module-cache-path /Users/alexmunzon/chess-builds/replay-sequence-2026-11-15/module-cache \
  native/ChessCompanionVision/{ImageDecoder,PixelFeatures,SyntheticRecognizer,NativeVisionCLI}.swift \
  -o /Users/alexmunzon/chess-builds/replay-sequence-2026-11-15/bin/chess-native-vision
python3 -B native/ChessCompanionVision/conformance.py \
  --binary /Users/alexmunzon/chess-builds/replay-sequence-2026-11-15/bin/chess-native-vision \
  --corpus "$OUT" --out /Users/alexmunzon/chess-builds/replay-sequence-2026-11-15/native-conformance.json
npm test
```

Without `REPLAY_SEQUENCE_DIR` the replay test skips, so plain `npm test` stays 172 pass, 2 skipped.

## Measured (2026-11-15, Mac)

- Two selector runs gave byte-identical manifests (SHA-256 `0c2a46b3…bd8ad`).
- The test runs each PNG through the real Python synthetic recognizer (`recognizeSimulation`),
  feeds the boards to `src/core/device-game-session.js` after one automated starting-state review
  fixture, and checks: all 7 stable positions track to the expected full FEN and move; the occluded
  frame (16 unknown squares) gives `uncertain-squares` and revokes tracking; later good frames stay
  blocked until a new review; `guidanceAllowed` and `liveGuidanceAllowed` are never true.
- Native Swift vs Python: 15 frames, 960 squares, 0 decision disagreements, geometry agrees on all.

## Limits

Synthetic known-template images with colored markers, reused from the existing corpus: not physical
boards, not a camera or glasses test, not held-out accuracy. No capture, castling, en passant or
promotion is in the chosen segment. The starting-state review is an automated fixture, not a human
review. Mac CPU only; no iPhone run.
