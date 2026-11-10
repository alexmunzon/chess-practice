# Chess Companion delivery plan

Updated November 10, 2026. The user pivoted the glasses project from blackjack to chess and asked for a properly planned, comprehensive build using reusable parts. The blackjack repository remains preserved next door. This companion is for private practice or assistance permitted by everyone involved, not covert competition use.

## Product contract

Capture a board, review uncertain pieces and historical game state, validate the position, obtain a strong legal move locally, and present it without allowing stale results to survive a changed board. Bounded Stockfish analysis is strong analysis, not proof of optimal play. No camera system can infer side to move, castling rights, en passant or repetition history from a single board image.

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

## Phase 3: board calibration — implemented experimental CLI, not robust recognition

- Reused Apple ImageIO/Vision rectangle/CoreImage perspective code from the old evaluation lab.
- Automatic quadrilateral proposals, reviewed manual four-corner fallback, orientation, normalized board, source-grid overlay, 64 projected square polygons.
- Acceptance: synthetic perspective/rotation/glare controls, blur/covered negatives, invalid geometry, orientation and explicit calibration review.
- Current evidence: 4/5 synthetic positives proposed a board; 2/2 negatives rejected. One real physical-board photograph produced no candidates. This is a small diagnostic sample, not an accuracy estimate.
- Next: improve grid geometry using line intersections and verify manual ground truth on independent real physical boards. Integrate reviewed calibration into the app only after the CLI boundary is tested.

## Phase 4: pieces and continuous game state — not implemented

- Establish a licensed, disjoint development and held-out evaluation set of actual chess boards, including multiple piece sets, camera angles, lighting, clutter, hands, motion, occlusion and orientation.
- Use a replaceable piece-classifier interface returning per-square label probabilities and explicit unknowns; never manufacture FEN from calibration alone.
- Score separately: board detection/geometry, piece identity/color, exact board, legal complete position, false confident suggestions, abstention and latency. Keep source-level split to avoid correlated-frame leakage.
- Begin from human-confirmed setup, then compare candidate observations only against legal successor states. Ambiguity, multiple skipped moves, loss of view or manual corrections must stop suggestions and request review.
- Dependency: compatible locally runnable model, usable training/evaluation data and its license. No model download, training service, remote image upload or accuracy claim has been approved merely by this plan.
- Gate: benchmark measured on independently labeled real images/video before camera integration. Define acceptance thresholds from a measured baseline, not invented success percentages.

## Phase 5: capture and glasses — blocked on device details and hardware

- Introduce CaptureSource interface for prerecorded frames first, then phone camera, then supported glasses SDK. Carry sequence, monotonic time, source identity and session epoch with every frame.
- Reuse replay lifecycle and stale-session principles from blackjack; no existing real camera/Bluetooth/glasses implementation exists to transfer.
- Confirm glasses model, OS, public SDK, camera access, supported resolution/rate, phone pairing, audio/display capability and developer signing requirements before choosing a transport.
- Keep camera/microphone/Bluetooth permissions explicit. Use no cloud image transmission by default. Store no captured frames unless deliberately enabled.
- Gate: physical device capture, interruption/reconnect/background/battery/heat/latency tests; permission-denied and disconnect states clear guidance. Device-specific work cannot be verified without the actual device.

## Phase 6: output, robustness and release

- Spoken/visible advice only from a currently confirmed position. Include human-readable move, promotion and check/mate context. Allow immediate stop and repeat, avoid speaking stale moves.
- Audio/glasses overlay remains an adapter to build after capability confirmation, not a feature already present.
- Security: loopback-only server, same-origin/Host checks, static allowlist, bounded JSON, CSP, no remote analysis, no keys or telemetry. Test browser interruption and resource cleanup.
- Distribution: preserve BSD chess.js and GPL Stockfish notices, exact locked versions and corresponding source availability. Review packaging obligations before distributing engine binaries. No deployment or external sharing in this milestone.
- Hardware acceptance is separate from offline tests. Deliver reproducible commands and failures as well as successes.

## Immediate work queue

1. Completed integrated browser/API tests and explicit piece-placement/history editing. Keep these regressions passing.
2. Completed a separate labeled-observation replay/tracking seam with stable identity and legal successor checks. This is not image recognition and is not yet wired to the UI.
3. Bring manual calibration into the review workflow, then evaluate a larger independently labeled physical-board set.
4. Connect real recognizer observations to the existing temporal state seam and analysis UI only after measured recognition reliability. Then select a supported physical glasses adapter.
