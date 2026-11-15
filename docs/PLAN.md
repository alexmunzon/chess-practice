# Chess Companion delivery plan

Updated November 11, 2026. The user requires the complete runtime **on iPhone 17 / iOS 27.2**, without a Mac runtime service. The Mac remains development/evaluation tooling. The user has no physical chessboard, so development follows [SIMULATION_PLAN.md](SIMULATION_PLAN.md): legal games, rendered image/video recognition, then later authorized glasses capture of a screen board. Layers 1–2 are implemented and verified on generated PNGs and decoded MP4 frames; bounded native modules now exist and a Mac WebKit engine fixture passed. A complete installed/tested iPhone app remains pending. Exact results and limits are in VERIFICATION.md. The manual photo/corner review workflow is implemented and tested. Physical-video recognition and CoreML numerical validation remain failed gates. Missing photo history stays unset and uncertainty revokes queued speech. Existing work and blackjack remain preserved.

Original baseline: November 10, 2026. The user pivoted the glasses project from blackjack to chess and asked for a properly planned, comprehensive build using reusable parts. The blackjack repository remains preserved next door. This companion is for private practice or assistance permitted by everyone involved, not covert competition use.

## Product contract

Capture a board, review uncertain pieces and historical game state, validate the position, obtain a strong legal move and speak it with all runtime computation on the iPhone. No stale result may survive a changed board. The computer server and photo evaluator are test tools, not runtime dependencies of the phone design. Bounded Stockfish analysis is strong analysis, not proof of optimal play. No camera system can infer side to move, castling rights, en passant or repetition history from a single board image.

## Phase 1: trusted chess core — implemented and integration-tested

- Pinned chess.js rules and Stockfish 19 full single-thread NNUE WASM, local-only execution.
- Six-field FEN, structural position checks, legal moves, promotions, castling and en passant.
- Bounded search (maximum three seconds), child-process deadlines and cancellation, legality validation of returned moves.
- Acceptance: reference perft 20/400/8902 and Kiwipete 48/2039; special-move, checkmate/stalemate, invalid-position and mate-in-one tests; no move without confirmation.
- Limitation: structural validity is not proof of historical reachability. Imported FEN has no repetition history. Preserve and track move history before claiming full draw adjudication.

## Phase 2: usable review and analysis — implemented and integration-tested

- Responsive keyboard-accessible board, legal practice moves, promotion choice, flip, undo, FEN editor and local reference image.
- Separate explicit confirmation of pieces, side, castling and en passant before each analysis.
- Position change, draft edit, cancel, visibility interruption or new request invalidates previous output. Late callbacks cannot restore it.
- Acceptance: browser flow from starting board to legal move to confirmed analysis; invalid-FEN recovery, cancellation, stale-result tests, local image preview and offline privacy checks.
- Explicit piece-placement and game-state controls are implemented and tested. Setup is an unvalidated draft until server validation succeeds; confirmation remains separate.
- Manual photo review now includes image-bound corner selection, canonical orientation and explicit calibration review. Recognition creates a draft only; complete historical state and position confirmation remain separate. Software tests cover the workflow, not physical recognition accuracy.

## Phase 3: board calibration — implemented experimental CLI, not robust recognition

- Reused Apple ImageIO/Vision rectangle/CoreImage perspective code from the old evaluation lab.
- Automatic quadrilateral proposals, reviewed manual four-corner fallback, orientation, normalized board, source-grid overlay, 64 projected square polygons.
- Acceptance: synthetic perspective/rotation/glare controls, blur/covered negatives, invalid geometry, orientation and explicit calibration review.
- Current evidence: 4/5 synthetic positives proposed a board; 2/2 negatives rejected. One real physical-board photograph produced no candidates. This is a small diagnostic sample, not an accuracy estimate.
- Manual calibration is now integrated into the review workflow and tested, including image identity, orientation and crop-coordinate boundaries. No accuracy claim follows from those software tests. Physical-board geometry improvement and independent ground truth remain future evaluation work; synthetic visible-marker geometry is a separate development track.

## Phase 4: pieces and continuous game state — experimental, recognition gate failed

Saved-photo CoreML/ONNX diagnostic implementations and reviewed legal observation tracking exist. The photo API/UI returns drafts only; autonomous vision-to-engine integration is disabled. Real-video performance and numerical validation do not qualify these classifiers for live advice. Remaining work:

- Establish a licensed, disjoint development and held-out evaluation set of actual chess boards, including multiple piece sets, camera angles, lighting, clutter, hands, motion, occlusion and orientation.
- Use a replaceable piece-classifier interface returning per-square label probabilities and explicit unknowns; never manufacture FEN from calibration alone.
- Score separately: board detection/geometry, piece identity/color, exact board, legal complete position, false confident suggestions, abstention and latency. Keep source-level split to avoid correlated-frame leakage.
- Begin from human-confirmed setup, then compare candidate observations only against legal successor states. Ambiguity, multiple skipped moves, loss of view or manual corrections must stop suggestions and request review.
- Dependency: compatible locally runnable model, usable training/evaluation data and its license. No model download, training service, remote image upload or accuracy claim has been approved merely by this plan.
- Gate for automatic assistance with physical pieces: benchmark measured on independently labeled real images/video. Define acceptance thresholds from a measured baseline, not invented success percentages. Glasses capture of a virtual screen board under `SIMULATION_PLAN.md` is a separate acceptance track and does not establish physical-piece generalization.

## Phase 5: capture and glasses — target confirmed, native and hardware validation pending

- A bounded offline `RecordedFrameQueue` now carries sequence, monotonic time, source/frame hashes and session epoch; it retains one active and one latest pending frame. Real saved-photo processing and cancellation were exercised. It emits review-only proposals, has no engine/audio connection, and is not a camera SDK adapter. See `LIVE_PIPELINE.md` for its contract and measured latency.
- The synthetic replay driver is implemented under `SIMULATION_PLAN.md`; its image-recognition results remain separate from real footage. The Swift synthetic recognizer matches the frozen Python decisions over 78 reused PNG frame records / 4,992 square decisions on the Mac, with zero disagreements including abstentions. Its iOS typecheck excludes real package resource bundling. Later glasses capture of a screen board remains a distinct hardware test requiring explicit device authorization.
- Reuse replay lifecycle and stale-session principles from blackjack; no existing real camera/Bluetooth/glasses implementation exists to transfer.
- Target is Ray-Ban Meta Wayfarer Gen 1 and the user-confirmed iPhone 17 / iOS 27.2, with all runtime work on the phone. DAT 1.0.1 resolved to the pinned revision. Earlier generic simulator/device `xcodebuild` checks exited before compilation with an iOS 26.2 destination/platform error; subsequent inventory confirmed installed SDKs, and Swift 6.2.4 successfully typechecked and unsigned-linked a minimal device-target DAT import library using the installed iPhoneOS 26.2 SDK. No SDK installation or upgrade was needed for that probe. Full app build/deployment, pairing, camera frames and audio remain unverified; see `HARDWARE_COMPATIBILITY.md`.
- Native capture/review/output contracts passed 10 Mac mock lifecycle checks and a direct iOS/DAT typecheck. The dormant adapters require an explicitly supplied authorized session; no registration or device operation ran. Media presentation timestamps and receipt time remain separate: real DAT frame capture age is unknown and therefore blocks engine/speech permits. A validated clock mapping is required before live guidance.
- The phone-local rules/Stockfish WebKit host source typechecks for iOS. After separate browser and expanded-command approvals, the isolated nonpersistent Mac WebKit harness loaded the local bundle, returned a legal Stockfish move and checked cancellation in about 1.48 seconds. Its first restricted-sandbox attempt could not start WebKit services and remains preserved. App packaging and iPhone memory/performance remain separate gates; the subsequent entry cancellation guard is source/typecheck evidence, not a second WebKit execution.
- Keep camera/microphone/Bluetooth permissions explicit. Use no cloud image transmission by default. Store no captured frames unless deliberately enabled.
- Gate: physical device capture, interruption/reconnect/background/battery/heat/latency tests; permission-denied and disconnect states clear guidance. Device-specific work cannot be verified without the actual device.

## Phase 6: output, robustness and release

- Spoken/visible advice only from a currently confirmed position. Include human-readable move, promotion and check/mate context. Allow immediate stop and repeat, avoid speaking stale moves.
- Browser local speech, a text-only adapter and dormant native speech source are implemented; phone/glasses output is not validated. Official iOS issue #358 reports streamed camera sessions muting phone audio/TTS on Gen 2. The native coordinator requires a matching stream-stop acknowledgement before permitting its explicitly enabled speech experiment; that guard does not prove audio recovery. Gen 1 behavior and actual audibility must be tested. Displayless Gen 1 has no visual overlay.
- Security: loopback-only server, same-origin/Host checks, static allowlist, bounded JSON, CSP, no remote analysis, no keys or telemetry. Test browser interruption and resource cleanup.
- Distribution: preserve BSD chess.js and GPL Stockfish notices, exact locked versions and corresponding source availability. Review packaging obligations before distributing engine binaries. No deployment or external sharing in this milestone.
- Hardware acceptance is separate from offline tests. Deliver reproducible commands and failures as well as successes.

## Immediate work queue

Continue [SIMULATION_PLAN.md](SIMULATION_PLAN.md) with iPhone-local integration. Layers 1–2 already pass the frozen known-template corpus: both PNG and decoded-video runs accepted all 68 positive frames exactly, withheld guidance on all 10 challenge frames and matched all 34 required legal-state checkpoints. The lack of a physical board or accessible public footage does not block those layers. Synthetic-domain results must not qualify either physical-photo model for automatic advice.

The WebKit scheduling timeout is resolved on Mac. All five offline Simulator fixtures have now been exercised: four produced separately rules-checked recommendations; obstruction blocked advice with 16 unknown squares. Actual UI review, invalid FEN, reset and background checks passed. The freshly compiled mock lifecycle suite passed 10/10, including held late replies after switching. Exact actual-UI in-flight fixture-switch timing remains unverified because CUA navigation cannot reliably reach the same one-second search window. See HANDOFF.md and the November 13 quickstart/evidence. The same local Simulator scope is approved; no code defect or additional permission blocker was found. Physical iPhone, glasses and audible output remain separate. Preserve unknown live capture age as a hard output gate.

The manual photo/corner workflow is complete with software tests, including image identity, orientation/crop mapping, EXIF dimensions, stale-result rejection and explicit initial-state review. Its proposal stays review-only. It is available alongside simulation but is not evidence of new real-board classifier accuracy.

The bounded CoreML investigation and subsequent authorized GPU-visible comparison are complete; see `NUMERICAL_DIAGNOSIS.md`. Apple M1 was visible and all four passes per synthetic reference exactly recovered historical outputs, but **1/2,496 logits still failed tolerance**, with all 192 labels matching. The larger earlier restricted-run discrepancy is separately preserved. Reproducing historical outputs is no longer an environment dependency; resolving the remaining numerical outlier still requires evidence, and no correction has been established. The inherited CPU-only reporting bug was fixed, but the model and production runner were not changed. No optimized runner, relaxed tolerance or threshold was adopted.

The older recorded-photo queue measurements were 11.58/11.42 seconds and the one-second cancellation guard worked. Later authorized CoreML reference predictions were **152.88–406.45 ms**, with **1,447.30 ms** shared compile/load. These different runtime conditions and synthetic tensor inputs are separately recorded; neither is a camera-to-speech latency benchmark or justification for changing the production freshness guard. A persistent/single-pass physical-photo runner remains unadopted.

Two distinct-author public sources were found, but initial DNS failures were followed by explicitly authorized one-attempt downloads that both returned **HTTP 403 Forbidden**. Those routes are closed; no retry/bypass, footage, labels or scores followed. See `PUBLIC_VIDEO_SOURCES.md`. A future real-video experiment still needs accessible licensed media and independently frozen labels. It is separate from immediate synthetic work.

The recorded-artifact paired evaluator remains development replay, not a new held-out experiment. See `PAIRED_EVALUATION.md`; do not tune on the five reused frames and relabel them as a fresh holdout. Keep completed review/API/legal-tracking regressions passing during phone integration. An optional ordinary glasses capture of the displayed board can test optics without an SDK; continuous capture still needs the native adapter integrated and explicitly authorized device setup. Physical-piece generalization and real audible delivery remain further independent gates.
