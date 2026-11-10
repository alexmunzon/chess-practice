# Offline observations and legal state tracking

This module is a prerecorded **label** replay seam, not a vision system. All bundled examples/tests are **synthetic observations** generated from chess.js positions. No image classifier, camera, microphone, glasses transport, hardware validation, model download or image upload is implemented here. It is not yet wired into the UI or analysis endpoint.

## Run

From the project root with the existing local dependencies:

- `node --test tests/observation.test.js`
- `node scripts/replay-observations.js --synthetic-demo`
- `node scripts/replay-observations.js --emit-synthetic-demo > /your/authorized/path/replay.json`
- `node scripts/replay-observations.js /your/authorized/path/replay.json`
- `node scripts/replay-observations.js --emit-synthetic-demo | node scripts/replay-observations.js -`

The demo reviews the starting position, stabilizes it, observes e4 twice, then times out. Output contains no engine recommendation, only state and guidance eligibility. The demo's `reviewed` flags are simulated human input for a synthetic test, not permission to automatically confirm real observations.

## Future recognizer interface

`validateObservation(frame)` validates and clones the following exact structure. Unknown keys are rejected. A frame has sourceId (1–128 ASCII identifier characters), positive safe-integer epoch, nonnegative safe-integer sequence, capturedAt (nonnegative monotonic milliseconds), and squares. `squares` has exactly a1–h8, each with `{ label, confidence }`. Labels are `empty`, `unknown`, or FEN piece letters `PNBRQKpnbrqk`. Confidence is finite in [0,1]. No omitted cells, occupancy-only labels, probabilistic guesses or automatic empty defaults are accepted. A future classifier must explicitly choose unknown when unsure; confidence is an adapter input, not proof of correctness.

Canonical coordinates must come from a separately reviewed orientation/calibration. Labels do not include images, image paths or blobs. Individual observations are bounded to 16 KiB after validation; the strict schema also bounds all variable-length fields. A future untrusted transport must enforce its byte limit before JSON parsing and invoke this validator before using labels. The provided replay reader limits input to 2 MiB and 2,000 events.

An actual recognizer adapter will need to emit this shape after processing real images. Implementing the interface is not an accuracy benchmark. Independent real-board recognition evaluation remains required.

## Lifecycle and safety contract

1. Construct `ObservationTracker({ clock })` with the capture source's monotonic clock domain. Defaults are two distinct stable frames spanning at least 50 ms, 1,000 ms freshness/timeout and confidence >= 0.95 on every square. These are conservative demo settings, not validated recognition thresholds. Options are bounded.
2. `connect(sourceId)` creates a new epoch. Read the returned epoch and stamp it onto callbacks when capture starts, not when callbacks finish. Reconnecting even the same source invalidates the old session. Never substitute the current epoch onto an old callback.
3. A person reviews a complete six-field FEN, including side, castling, en passant and move counters. Call `confirm({ fen, reviewed: { pieces:true, turn:true, castling:true, enPassant:true, counters:true } })`. Structural validation uses the existing core. It cannot prove historical reachability. Confirmation alone does not allow guidance.
4. Call `ingest(frame)` in callback order. Sequences and capture timestamps must strictly increase within the epoch. Repeated/reordered callbacks do not count toward stability or replace newer state. Pre-confirmation callbacks cannot establish stability. Wrong-source frames in the active epoch invalidate confirmation. Old epochs are ignored. Fresh unknown/low-confidence cells, invalid frames, impossible/ambiguous transitions and stale/future frames require renewed human review.
5. Reconcile the full observed board against the confirmed board and its zero/one-ply legal successors. Require the same candidate in distinct frames over the stability interval before advancing. Intermediate hand movement or partially moved pieces causes abstention, not reconstruction. Castling, en passant, captures and all four promotions use chess.js legal moves. Historical rights derive only from the confirmed FEN and tracked legal moves.
6. `edit()`, `disconnect()` or `connect()` clears guidance and requires reconfirmation. `tick()`/`snapshot()` checks timeout. A frame after a timeout cannot automatically restore trust. Unknown/low-confidence frames are deliberately stricter than partial-board inference, even when visible cells seem to identify one move.
7. Call `snapshot()` immediately before requesting or presenting analysis, and regularly call `tick()` while streaming. Require `guidanceAllowed === true`. Capture sourceId, epoch, revision and FEN with each analysis request. Recheck all four and guidance eligibility immediately before showing/speaking its result. A fresh, high-confidence observation identical to an already-ready board renews freshness without changing revision or readiness, allowing asynchronous searches to finish during continuous streaming. A changed board immediately clears readiness and changes revision; uncertainty and lifecycle invalidation also change revision. Async consumers must discard results when the checked identity/state changes. This tracker is not a timer, analysis coordinator or output adapter, so it cannot retract output that a consumer ignores. The retained FEN and lastMove in a non-ready snapshot are historical context, never permission for guidance.

Complete visible labels normally make zero/one-ply candidates unique; an explicit ambiguity branch still abstains. Skipped moves whose resulting board is not a zero/one-ply successor are rejected. No label-only tracker can detect an unobserved reversible multi-move cycle that returns to the same visible arrangement, or determine reliable move history during missing capture. Sequence gaps alone can mean dropped identical frames; freshness and legal matching do not prove uninterrupted play. Human reconfirmation is required whenever the source reports lost view/continuity, by invoking edit/disconnect. Imported FEN has no prior repetition history; `historyComplete` is always false. No full-game draw-history guarantee is made.

## Replay JSON

Top level: `{ "version": 1, "kind": "synthetic-observations", "events": [...] }`. The other allowed kind, `recognizer-observations`, names future external label recordings only; it does not assert that a classifier is available or accurate.

Every event carries `type` and `at` (nonnegative, nondecreasing monotonic receipt milliseconds). Supported exact event fields:

- `connect`: additionally `sourceId`.
- `confirm`: additionally `fen` and the five-boolean `reviewed` object above.
- `observation`: additionally `frame` with the recognizer shape above. `capturedAt` may precede receipt `at`, within freshness bounds.
- `tick`, `edit`, `disconnect`: no additional fields.

Use `--emit-synthetic-demo` for a complete schema-valid input. Invalid replay structure or JSON exits nonzero. A malformed observation inside a valid replay produces a fail-closed state with an error field, so subsequent lifecycle behavior can still be inspected. The CLI reads local JSON or stdin only and never launches an engine or accesses hardware/network.

Claimable 50-move and threefold-repetition draws are not treated as automatic termination. Candidate enumeration uses the shared core position status; imported FEN cannot establish earlier repetition history, and this seam does not provide full-game draw adjudication. A synthetic test at halfmove 100 verifies that a legal successor remains observable.
