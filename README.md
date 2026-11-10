# Chess Companion

A local chess practice prototype: review a board, confirm its complete state and get a strong legal move from Stockfish. The old blackjack project is preserved alongside this new repository.

## Run

Requires Node.js 22 or newer. From this directory:

```sh
npm ci --ignore-scripts
npm test
npm start
```

Open http://127.0.0.1:4174 in the same computer's browser. The server binds only to loopback. Installation fetches the exact locked official-registry dependencies; normal analysis runs locally. Stop the server with Ctrl+C. Nothing is deployed, submitted to a chess service or played against another person.

## Use

1. Start from the initial position, enter a complete FEN, or choose **Edit pieces & state**. In manual setup, select a piece/eraser and click board squares. Set side to move, castling rights, en passant and move counters, then **Validate setup**.
2. If comparing a physical board, choose a local reference image. This is manual comparison, not automatic piece recognition. The image is displayed from a browser-local object URL, not sent to the server.
3. Check all pieces and game state, then tick the confirmation box and **Find best move**. Choose 0.5, 1.5 or 3 seconds of search. Evaluation is from the side-to-move perspective. The engine line is a possible continuation, not a commitment or guaranteed result.
4. Click a piece and legal destination to play a local practice move. Choose promotion type before moving. Every move, FEN edit, manual setup, cancellation or hidden-tab interruption clears guidance and requires renewed confirmation.

FEN cannot establish earlier repetition history or prove that a position was historically reachable. The fifty-move threshold is claimable rather than automatic; the seventy-five-move threshold terminates play unless the position is checkmate. Full-game repetition adjudication is not implemented. Manual setup never silently infers castling or en passant from piece locations. Imported positions are structurally validated, including king safety, material limits and historical-right consistency, but they are not retrograde proofs.

## What exists

- Locked chess.js 1.4.0 and full Stockfish 19.0.1 single-thread NNUE WASM.
- Legal move, promotion, mate/stalemate and draw-state handling; bounded local engine processes with timeout/cancellation.
- Responsive board, FEN and piece-placement editor, explicit confirmation, undo/flip, local image reference, stale-result guards.
- Experimental macOS board-corner calibration CLI with reviewed manual fallback and 64-square mapping.
- Offline observation replay/state tracking is separate from the browser and accepts labeled observations, not raw image recognition. See `docs/OBSERVATIONS.md` when present.

## What does not exist yet

Automatic physical piece recognition, dependable real-camera board detection, live phone/glasses capture, Bluetooth integration, audio guidance and hardware validation. The first real physical-board photo produced no automatic rectangle candidate. Neither synthetic images nor synthetic labeled observations are real-world accuracy evidence. Bounded engine analysis is not a promise of perfect chess.

## Plan and evidence

- `docs/PLAN.md`: phased implementation, acceptance gates and dependencies.
- `docs/REUSE.md`: actual reuse versus patterns and missing hardware code.
- `docs/VERIFICATION.md`: measured tests and browser checks.
- `native/BoardVision/README.md`: calibration commands, public photo source and honest failures.
- `evidence/`: test output, dependency audit and screenshots of actual local UI results.

## Privacy, security and distribution

Loopback-only server, same-origin/Host validation, bounded request bodies, static allowlist and Content Security Policy. No remote analysis, analytics, credentials, camera or microphone access. Advice is for private practice and assistance permitted by those involved.

`package.json` declares GPL-3.0-or-later. Third-party license texts and corresponding upstream sources are recorded in `THIRD_PARTY_NOTICES.md` and `licenses/`. Do not redistribute `node_modules`, the Stockfish binary/WASM or a bundled release until GPL corresponding-source delivery requirements are verified. The local development prototype uses locked npm installation; no public release is part of this milestone.
