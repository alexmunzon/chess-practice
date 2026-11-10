# Verification — November 10, 2026

Environment: user's Mac, Node 24.21, installed Apple Swift/Vision/CoreImage and Python/Pillow/NumPy. Local loopback only. No camera, microphone, Bluetooth, glasses or external chess account used.

## Automated software tests

`npm test`: **55 passed, 0 failed**, approximately 2.1 seconds on this run. Complete log: `evidence/all-tests.txt`.

Coverage includes:
- Start-position perft 20/400/8902 and Kiwipete 48/2039.
- Castling, en passant, all promotion choices, mate, stalemate and material checks.
- Claimable fifty-move threshold versus automatic seventy-five-move threshold, with checkmate precedence.
- Rejection of impossible castling/en-passant state and promotion inventories; not a claim of full historical reachability validation.
- Real full Stockfish startup, legal best move, mate in one, bounded search, illegal-output rejection and actual child-process cancellation (about 104 ms in the test).
- Human review, stale/foreign request rejection, FEN mismatch, cancellation and interruption.
- Delayed move responses: the actual app's event handlers disable confirmation/analysis during mutation, recover after failure and discard superseded responses. This is a minimal DOM test harness, not a second browser test.
- Loopback Host/Origin rejection, unsupported paths, content type, oversized JSON, static asset allowlist/CSP and real HTTP-to-Stockfish result.
- Twenty-six synthetic labeled-observation replay/tracker tests. These cover special moves, unknown/low-confidence squares, timeouts, source/epoch/sequence ordering, repeated observations, stable frame spans, identical-board revision preservation, changed-board invalidation and bounded replay. **These are not image recognition tests.**

`npm audit --omit=dev`: **0 vulnerabilities** reported. This is the registry audit result, not a comprehensive security certification. Evidence: `evidence/dependency-audit.txt`.

## Actual Chrome interaction

The browser loaded http://127.0.0.1:4174 and visibly confirmed:
- Initial board, manual e2–e4 practice move, explicit confirmation and Stockfish's legal e5 response. Observed depth 21, search elapsed 1,507 ms, score −0.26 for Black.
- Starting-board analysis returned e4 at depth 20, 1,503 ms. Search depth and chosen moves vary by runtime and budget.
- Invalid FEN removed analysis/highlights and disabled analysis; reset recovered.
- Cancel immediately cleared output and required confirmation again.
- Checkmate showed no legal move and disabled analysis.
- Board flip changed first displayed square from a8 to h1 and back.
- Manual setup rejected an empty board for missing kings. Placed White king g6, White queen f7 and Black king h8, validated, confirmed and obtained **Qg7#**, mate score 1. This was a manually entered board, not recognized from an image. The engine reported depth 245 after 54 ms for this trivial forced mate; depth is engine output, not an independent strength metric.
- Final correction checks: halfmove 100 remained analyzable with a draw-claim status; eight white pawns plus two queens was rejected.

Screenshots: `evidence/chess-ui-2026-11-10.jpg` and `evidence/chess-manual-mate-2026-11-10.jpg`. No mobile viewport, local-file chooser, audio, phone or glasses test is claimed.

## Board calibration lab

Recompiled with `swiftc native/BoardVision/BoardCandidates.swift -o /tmp/chess-board-candidates`, then reran `python3 tests/vision_calibration.py /tmp/chess-board-candidates /tmp/chess-vision-benchmark-integration`. Evidence: `evidence/vision-tests.txt`.

- Four of five synthetic positive scenes proposed boards: frontal, perspective, rotation and glare. Blur abstained.
- Two negative controls, covered and plain rectangle, abstained.
- Detected synthetic mean corner error: 9.74–11.27 source pixels on 800×800 scenes.
- Manual four-corner mapping/orientation, 64-square grid, geometry rejection and human-confirmation gates passed.
- One real physical chessboard photo, Staxringold's Wikimedia CC BY-SA 3.0 starting position, produced **no automatic candidates**. Source/license and result: `native/BoardVision/README.md` and `benchmark-2026-11-10.json`.

This tiny diagnostic set is not real-world accuracy evidence. No piece classifier or FEN-from-image capability exists. Automatic calibration remains experimental; manual calibration is separate from confirming a complete chess position.

## Review corrections incorporated

An independent read-only review found three medium issues: claimable draw treated as terminal, impossible promotion inventory accepted, and a pending-move analysis race. All were corrected with new regression tests and final browser checks where applicable.

## Remaining gates

Independent real-image/video recognition dataset and classifier; calibrated confidence/abstention evaluation; integration of actual recognizer observations with state tracking and UI; complete move-history/repetition adjudication; phone/glasses SDK/device compatibility, capture permissions/transport, interruption/reconnect tests, output/audio and on-device heat/battery/latency. Current observation tracking is a tested standalone seam, not wired into browser analysis. Source-only prototype packaging does not constitute GPL binary-distribution review.
