# Chess Companion

A local prototype toward live Ray-Ban Meta Gen 1 chess assistance. The user-selected target is an entirely **iPhone-local runtime** on iPhone 17 / iOS 27.2: capture, recognition, legal state tracking, Stockfish and speech, with no Mac runtime service. The current computer app remains a development test bed. Reliable physical-board recognition and glasses capture/audio are not ready. The old blackjack project is preserved alongside this repository.

## Run

The computer test bed requires Node.js 22 or newer. From this directory:

```sh
npm ci --ignore-scripts
npm test
npm start
```

Open http://127.0.0.1:4174 in the same computer's browser. The server binds only to loopback. Installation fetches the exact locked official-registry dependencies; normal analysis runs locally. Stop the server with Ctrl+C. Nothing is deployed, submitted to a chess service or played against another person.

## Simulation without a physical board

The simulation milestone is runnable. It generates legal games as pixels and video, recognizes a known vector piece family using visible corner markers, and tests complete-state tracking, Stockfish and a text speech sink. This is a screen-board baseline; physical recognition and glasses audio remain separate gates. Existing installed Python 3, Pillow, NumPy and FFmpeg are used; nothing is downloaded by these commands.

```sh
node scripts/simulation/generate.mjs --out /tmp/chess-simulation --video
node scripts/simulation/evaluate.mjs --input /tmp/chess-simulation --out /tmp/chess-png-report.json
node scripts/simulation/evaluate.mjs --input /tmp/chess-simulation --out /tmp/chess-video-report.json --video /tmp/chess-simulation/pixels/sequence.mp4
```

Choose a new empty output directory. For an interactive test, start the app, choose a generated PNG, and click **Recognize simulated board**. Review every piece and supply all historical fields in the resulting editor before **Validate setup**, confirmation, analysis and speech. Do not replace the recognized draft with FEN if testing vision. The first generated frame is an explicitly known new-game fixture: White, KQkq, no en passant, halfmove 0, fullmove 1. Other frames have different state.

Both final PNG and decoded-MP4 evaluations passed: 68/68 positive frames exact, all 10 challenge frames blocked guidance, 34/34 required legal-state checkpoints correct. These correlated frames use one known artwork family, not physical or unseen-style accuracy. See `docs/SIMULATION_PLAN.md` for the implemented plan, splits, commands and remaining gates.

## Use

1. Start from the initial position, enter a complete FEN, or choose **Edit pieces & state**. In manual setup, select a piece/eraser and click board squares. Set side to move, castling rights, en passant and move counters, then **Validate setup**.
2. Choose a local reference image for manual comparison. Optionally **Recognize saved photo** using the existing local Mac evaluator, or import its matching recognition JSON. Recognition sends the image only to the loopback service and returns an untrusted draft. The experimental classifier makes confident errors on real video. Review every piece and explicitly supply turn, castling (including none), en passant and both counters; missing state blocks validation. No photo can establish these historical fields. A model/evaluation setup must already exist; nothing downloads automatically.
3. Check all pieces and game state, then tick the confirmation box and **Find best move**. Choose 0.5, 1.5 or 3 seconds of search. Evaluation is from the side-to-move perspective. The engine line is a possible continuation, not a commitment or guaranteed result.
4. After confirmed analysis, **Speak move on this device** uses an installed local English browser voice. Audible delivery and glasses routing have not been tested. Click a piece and legal destination to play a local practice move. Choose promotion type before moving. Every move, FEN edit, manual setup, cancellation or hidden-tab interruption clears guidance and requires renewed confirmation.

FEN cannot establish earlier repetition history or prove that a position was historically reachable. The fifty-move threshold is claimable rather than automatic; the seventy-five-move threshold terminates play unless the position is checkmate. Full-game repetition adjudication is not implemented. Manual setup never silently infers castling or en passant from piece locations. Imported positions are structurally validated, including king safety, material limits and historical-right consistency, but they are not retrograde proofs.

## What exists

- Deterministic synthetic PNG/video generator, isolated pixel recognizer, separate truth evaluator, and review-only simulation API/UI.
- Locked chess.js 1.4.0 and full Stockfish 19.0.1 single-thread NNUE WASM.
- Legal move, promotion, mate/stalemate and draw-state handling; bounded local engine processes with timeout/cancellation.
- Responsive board, FEN and piece-placement editor, explicit confirmation, undo/flip, local image reference, stale-result guards.
- Experimental macOS board-corner calibration CLI with reviewed manual fallback and 64-square mapping.
- Experimental saved-photo recognition API/UI with unknown-history fields, human review and stale-import guards. It is not trusted automatic recognition.
- Offline legal observation tracking and a camera/engine/speech coordinator seam, tested with reviewed synthetic-label fixtures and a text sink. Separate native adapter source now exists; it has not received real camera frames. See `docs/OBSERVATIONS.md` and `docs/LIVE_PIPELINE.md`.
- Bounded offline frame queue with source/frame hashes, freshness deadlines and cancellation. A real saved-photo request stayed review-only; the default one-second deadline cancelled it. Completed diagnostic requests took about 11.4–11.6 seconds, so this model path is not live-ready.
- Browser local speech control and stale-output cancellation; audible delivery is unverified.
- Swift synthetic recognizer: the existing 78 PNG frame records / 4,992 square decisions matched the frozen Python recognizer with zero disagreements, including abstentions, on the Mac. This is reused synthetic port conformance, not new accuracy or iPhone performance evidence.
- Swift capture/review/output contracts with 10 passing Mac mock lifecycle checks and dormant DAT 1.0.1 / native speech adapters. Real DAT capture age is still unknown, so real frames cannot receive engine or speech permits.
- Source for an iPhone-local WebKit rules/Stockfish backend, using bundled assets. Its native host typechecks, and an authorized Mac WebKit fixture passed local rules, actual Stockfish and cancellation. App integration and phone memory/performance remain unverified.

The installed iOS 26.2 SDK and Swift 6.2.4 successfully typechecked and unsigned-linked a minimal DAT 1.0.1 import library. The earlier generic `xcodebuild` destination error did not establish that the compiler SDK was absent. Native vision, capture and runtime sources also passed bounded iOS typechecks; these do not constitute a complete app build, signing, installation or hardware test. See `docs/HARDWARE_COMPATIBILITY.md` and `docs/VERIFICATION.md` for the evidence and limits.

A separate **offline synthetic-study iPhone app** now compiles and links as an unsigned private bundle. Its UI requires explicit engine start, pixel recognition, full FEN review, analysis and optional speech. Eight mocked lifecycle checks pass. It was never installed or launched; actual UI/pipeline behavior and audio remain unverified. See `native/ChessCompanionApp/README.md` for assembly commands and the exact scope. Live glasses mode remains unavailable.

## What does not exist yet

Reliable automatic physical-board/piece recognition, an installed and tested iPhone app, live phone/glasses capture, Bluetooth integration and hardware validation. Saved genuine-video diagnostics show 0/5 automatic board detections and 120/236 accepted known piece labels wrong for the whole-photo model; no automatic physical-vision-to-guidance path is enabled. The five frames are one correlated staged video with partial labels, not an accuracy benchmark or continuous-game test. Browser speech and synthetic pipeline tests do not validate glasses audio. Bounded engine analysis is not a promise of perfect chess.

## Plan and evidence

- `HANDOFF.md`: stopping checkpoint, exact results/artifacts, unfinished verification and the next bounded task packet.
- `docs/WORKFLOW.md`: the existing build/test/independent-review/checkpoint process, with no background controller.
- `docs/SIMULATION_PLAN.md`: implemented simulation-first milestone and optional later glasses capture of a screen.
- `docs/PLAN.md`: phased implementation, acceptance gates and dependencies.
- `docs/REUSE.md`: actual reuse versus patterns and missing hardware code.
- `docs/VERIFICATION.md`: current permitted test results, environment blockers and separately labeled historical browser checks.
- `docs/HARDWARE_COMPATIBILITY.md`: official Gen 1 requirements and unresolved camera/audio interaction.
- `docs/VIDEO_EVALUATION.md`: genuine-video evidence and the next sequential evaluation gate.
- `docs/PAIRED_EVALUATION.md`: strict same-classifier replay, partial-label denominators, failure analysis and prerequisites for a genuinely new held-out comparison.
- `docs/PUBLIC_VIDEO_SOURCES.md`: new public source candidates, licenses, failed acquisition attempts and inspection requirements; no new held-out footage has been evaluated.
- `docs/NUMERICAL_DIAGNOSIS.md`: preserved failed numerical gate, artifact/layout audit, one-versus-three-pass results, restricted-runtime comparison and authorized GPU-visible reproduction.
- `native/BoardVision/README.md`: calibration commands, public photo source and honest failures.
- `native/ChessCompanionVision/README.md`: Swift synthetic recognizer, reused-data conformance and package/resource limits.
- `native/ChessCompanionCapture/README.md`: bounded phone-local contracts, mock checks and unknown DAT capture-age blocker.
- `native/ChessCompanionRuntime/README.md`: local WebKit engine source, bounded Mac execution evidence and remaining iPhone gates.
- `evidence/`: test output, dependency audit and screenshots of actual local UI results.

## Privacy, security and distribution

Loopback-only server, same-origin/Host validation, bounded request bodies, static allowlist and Content Security Policy. No remote analysis, analytics, credentials, camera or microphone access. Advice is for private practice and assistance permitted by those involved.

`package.json` declares GPL-3.0-or-later. Third-party license texts and corresponding upstream sources are recorded in `THIRD_PARTY_NOTICES.md` and `licenses/`. Do not redistribute `node_modules`, the Stockfish binary/WASM or a bundled release until GPL corresponding-source delivery requirements are verified. The local development prototype uses locked npm installation; no public release is part of this milestone.
