# Simulation-first chess glasses build

Updated 2026-11-11. Alex has no physical chessboard. Build in this checkout, preserve blackjack and existing work, and use installed local tools. The target remains Ray-Ban Meta Wayfarer Gen 1 with the reported iPhone 17 / iOS 27.2. On November 11 Alex explicitly chose **all recognition, chess processing and speech on the iPhone, without a Mac at runtime**; the Mac is only a development/test machine. Simulation does not establish physical-board or glasses accuracy.

## Three layers

1. **Legal games and evaluator truth.** Generate legal games with pinned chess.js, including castling, en passant, promotion, capture, lost castling rights, counters and repetition examples. Store starting full FEN, moves and per-frame truth in a separate evaluator directory. A single image supplies no historical state. Initial complete-state review is separate from subsequent zero/one-ply legal tracking; repetition history remains explicitly incomplete after a FEN import.
2. **Images and video through actual recognition.** Render a known 2D piece family and visibly marked board, then vary perspective, motion, lighting, occlusion and board appearance. A bounded synthetic-domain recognizer receives image bytes only, locates the visible marks, rectifies the board and classifies square pixels against fixed piece templates. It cannot read sidecars, FEN, seeds, file names encoding positions or scene metadata. This is a controlled screen-board baseline, not a replacement for the failed physical-photo models. Freeze development and held-out scene/game seeds before evaluation. Report unseen piece styles and severe distortions as challenge cases, including failures and abstentions; never tune and relabel the same set as held out.
3. **Later glasses viewing the virtual board.** First, Alex can open the generated static PNG or MP4 on his screen and use ordinary capture on his already-paired glasses, then import/export that recording manually. This optional optics test needs no DAT app or SDK and does not block layers 1–2. Later, continuous capture → recognition → state → engine → glasses audio requires SDK/compiler readiness, app signing and explicitly authorized phone/glasses setup. Both are screen-board tests, not physical-piece validation; no purchase of a board is required.

Optional licensed real footage with independently labeled frames remains a separate future test of physical generalization. The two approved public downloads returned HTTP 403; those routes are closed and do not block layers 1–2.

## Ownership and concrete milestones

| Owner/module | Work | Acceptance |
| --- | --- | --- |
| Generator: `scripts/simulation/generate.mjs`, `render.py`, `appearance.py` | Legal fixtures, deterministic PNGs, truth sidecars, MP4 with installed FFmpeg | Every move legal; exact provenance/split/seed recorded; pixels contain no embedded truth metadata |
| Pixel recognizer: `scripts/simulation/recognize.py` | Visible marker geometry, fixed synthetic templates, explicit unknowns | Image-only API; missing markers, occlusion and unsupported appearance fail closed; no fabricated history |
| Integration: `scripts/simulation/evaluate.mjs`, local simulation UI/API | Read pixels, score separately, review initial state, track legal moves, bounded Stockfish and cancellable speech | Truth used only by evaluator/reviewer fixture; simulated review explicitly labeled; no uncertain/stale advice |
| Independent reviewer | Review boundaries and acceptance coverage | Fix actionable defects, rerun affected tests, then full project regression |

The first milestone is a reproducible PNG/video corpus and image-only baseline. The second is a runnable local demo and measured replay through the existing legal tracker/engine with a separately labeled speech sink. Existing photo/manual-review workflows remain available. Do not weaken physical-model numerical gates, recognition thresholds or the one-second production freshness guard to make the simulation pass.

## Commands and evidence

Implemented entry points (choose a new empty output directory):

```sh
node scripts/simulation/generate.mjs --out /tmp/chess-simulation --video
node scripts/simulation/evaluate.mjs --input /tmp/chess-simulation --out /tmp/chess-simulation-report.json
node scripts/simulation/evaluate.mjs --input /tmp/chess-simulation --out /tmp/chess-video-report.json --video /tmp/chess-simulation/pixels/sequence.mp4
npm start
npm test
python3 -B tests/simulation_pixels.py
```

Generated source media and evaluation reports stay outside the repository. User-facing copies go under the current continuation chat's `outputs/simulation-2026-11-11/`. Reports must state counts, exact-board/piece errors, false accepted cells, abstentions, timing, split identity and whether speech was text-only, rendered audio or actually heard. Record source hashes and the command/environment used. Existing tests and manual-photo evidence live in `outputs/completion-build-2026-11-11/`.

## Gates that stay closed

- No browser access, device permissions, live camera/microphone/Bluetooth, account setup, installations or OS/Xcode upgrade without Alex's approval.
- A recognizer proposal never confirms pieces/history. Unknown, ambiguous, missing, reordered or stale observations revoke guidance and speech. Manual edits and interruptions require renewed review.
- The approved DAT 1.0.1 probe is compile-only, signing disabled, generic destinations. Successful compilation is not glasses capture validation.
- CoreML still fails its unchanged numerical gate (one output outside tolerance in the authorized GPU-visible comparison); real-video recognition remains unreliable. Synthetic results cannot qualify either physical recognizer for automatic advice.

## Implementation status

Layers 1–2 are implemented and evaluated: 78 generated PNGs plus an exactly aligned 78-frame H.264 MP4 (10 fps, 7.8 seconds). On both source PNGs and decoded MP4 frames, 54/54 development and 14/14 held-out frames had exact accepted boards; 10/10 challenge frames withheld guidance. Zero accepted wrong squares; all 34 required stable legal-state checkpoints matched complete evaluator FEN, and all 15 stale-session probes blocked further engine/text output. Actual Stockfish produced one legal recommendation per replay. Speech evidence is text-only; the local browser speech button exists, but browser interaction and audible output were not exercised in this continuation.

This is a deliberately small known-template domain: held-out games/scenes share artwork and an initial opening position with development. Motion is stepped; glare is an opaque white patch approximation. It is not a real-time 10 fps pipeline: median wall time per image was about 268 ms (PNG) / 234 ms (MP4), while replay uses a deterministic clock. No physical-model gate or production freshness deadline changed.

Independent review corrected nonopaque-alpha inputs exposing hidden RGB pixels and an evaluator gap that could let exact images pass despite failed legal tracking. Initial reports and frozen thresholds remain preserved. Final reports are `png-report.json` and `mp4-report.json`, alongside `policy-freeze.json`, `final-policy-source.json`, `QUICKSTART.md` and final regression evidence in the continuation outputs folder. The UI action **Recognize simulated board** returns a draft; actual user review remains mandatory before analysis/speech.

DAT 1.0.1 resolved at the exact pinned revision. The original Xcode generic-destination probes stopped before compilation. Follow-up inventory proved both iOS 26.2 compile SDKs were already installed; direct Swift 6.2.4 device-target import and unsigned library linking then succeeded. The destination error remains separate and undiagnosed. No component installation, compiler upgrade, signing, registration, device operation or hardware success is claimed. Physical-photo recognition remains unreliable; the authorized CoreML comparison still fails 1/2,496 logits under the unchanged tolerance.


## On-iPhone software checkpoint

The next bounded implementation ports the known-template recognizer to Swift with bundled fixed appearance assets, exposes existing local chess rules and full single-thread Stockfish through a portable Worker interface, and adds native capture/review/analysis/speech identity contracts. No Mac HTTP server is part of the intended phone runtime. WebKit resources, engine and rules must be bundled locally; no CDN or remote analysis.

The native recognizer has matched the frozen Python decisions on all 4,992 cells of the existing 78-PNG corpus (37 distinct source images, including abstentions). A separate unchanged-harness comparison also matched all 4,992 decisions from 78 frames actually decoded from the MP4 with FFmpeg. These are reused-data port checks, not new holdouts or physical-camera results. Mac recognition medians were 39.34 ms for the PNG records and 41.70 ms for the decoded-video records; iPhone performance and native phone video decoding remain unmeasured.

Worker transport tests run the actual pinned engine in Node workers. With separate browser and expanded-command approvals, the nonpersistent Mac WebKit harness also passed local position validation, actual Stockfish output and cancellation in about 1.48 seconds. The default restricted-sandbox attempt failed to start WebKit services; both results remain preserved. The later pre-cancelled-task guard is checked separately by compilation/contracts, with no post-guard WebKit rerun. iPhone execution remains unverified. SDK capture source is compiled only, never run. DAT media PTS and host receive time remain distinct; unknown capture age blocks live guidance. New frames, uncertainty, edits, disconnection and expiration must cancel analysis and queued/playing speech. Stream-stop acknowledgement is a test prerequisite for speech, not a claim that the documented camera/audio issue is solved.

The capture coordinator currently implements reviewed single-frame lifecycle contracts, not continuous game tracking. Its frame-bound review expires with the frame. The portable legal tracker supports continuity in offline replay; connecting that reviewed game anchor to native frame/speech authorization remains a separate integration step. Initial human review must be allowed to finish before requiring fresh agreeing observations; recognition must never manufacture that review. No completed iPhone app or live advice is claimed from these modules.

Module ownership: `native/ChessCompanionVision` (native pixel recognition), `native/ChessCompanionCapture` (capture/review/speech lifecycle), `native/ChessCompanionRuntime` (local WebKit host), `src/core/worker-engine.js` (portable UCI), `src/core/device-backend.js` (local rules/analysis contract), and `scripts/build-device-runtime.mjs` (private local resource assembly). Build → focused tests → independent review → fixes → regression is required for each. No new installation, browser or device operation is authorized by these source changes.

The standalone `src/core/device-game-session.js` now wraps the real legal tracker with exact replay JSON commands, complete initial review, immutable frame identities and an explicitly supplied replay clock. Ten focused tests cover special moves, counters, uncertainty, skipped plies, stale epochs and invalidation. It always withholds engine/speech permission and is not yet bundled into the WebKit host or connected to native capture. The final Node suite after this addition and the native rules-response binding passed 172/172.

The offline synthetic-study SwiftUI app also compiled/linked as an unsigned private arm64 iOS bundle, with eight passing mocked lifecycle checks and independent review. It requires explicit recognition, complete FEN review, analysis and a separate offline speech action; it creates no live capture clock. It has never been installed or launched, and no audio was played. HANDOFF.md records this stopping checkpoint and the single queued bounded task; docs/WORKFLOW.md records the existing review cycle without background automation.
