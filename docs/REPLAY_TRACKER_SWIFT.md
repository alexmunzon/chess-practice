# Replay tracker: Swift adapter (contract side of docs/REPLAY_GAME.md)

`native/ChessCompanionIntegration/ReplayTracker.swift` (Foundation only, Swift 6). Not yet wired into
`NativeEngineRuntime.swift`, `prepare_app.py` or `Package.swift` (later packet).

## API
- `ReplayRequestBuilder.initialize / observe / invalidate / snapshot` build `ReplayRequest` (canonical
  sorted-key JSON with `mode:"trusted-replay"`, `clockDomain:"replay-synthetic-v1"`). They throw on
  anything the JS side rejects: incomplete `ReplayHumanReview`, non six-field FEN, bad ids, epoch 0,
  missing squares, bad labels or confidence, over 16384 bytes. There is no builder for any other kind.
- `ReplayReplyDecoder.decode(_:for:activeSession:) -> ReplayOutcome` is strict: exact key sets
  (top level and `state`, `session`, `lastFrame`, `lastMove`), `schemaVersion` 1, matching
  `requestId`/`kind`, `runtime`/`mode`, active session and epoch, `guidanceAllowed`,
  `liveGuidanceAllowed`, `historyComplete` all boolean false, `trackingReady == (status == "ready")`,
  an accepted observe must echo its own frame as `lastFrame`, `ignored` only on observe.
- `ReplayOutcome` is `.tracking(state)` or the single `.revokedRenewedReviewRequired(cause)`. Error
  replies (including `STALE_SESSION`), malformed replies, transport failures and a tracker state of
  `needs-confirmation` all map to revoked.
- `ReplayTracker` (MainActor) talks to a `ReplayTrackerTransport` (`submit(requestJSON:timeoutMilliseconds:)`).
  One request at a time; a concurrent call revokes and discards the in-flight reply. After any
  revocation or `invalidate`, every call except `initialize` returns revoked without sending.

## Proven (2026-11-15, outputs in /Users/alexmunzon/chess-builds/replay-tracker-swift-2026-11-15/)
- `ReplayTrackerChecks.swift`: 94/94 checks. All 28 golden pairs decode as expected (1-26 equal the
  golden values; 27 error and 28 needs-confirmation revoke); 27 Swift-built requests are semantically
  identical JSON to golden; 23 single-mutation negatives revoke; builder refusals; mocked client
  playback of steps 1-26, transport failure, concurrency, latch and invalidate.
- Node one-off: Swift-built requests fed to `ReplayRuntime.handle` give 28/28 replies deep-equal to
  golden (step 27 `analyze` sent verbatim from the fixture since Swift cannot build it).
- macOS compile and iOS (arm64-apple-ios17.2) typecheck with `-warnings-as-errors`, alone and beside
  the existing integration sources.

## Not proven
No WebKit, Simulator or device run; no real transport; synthetic observations only. Nested echoed
keys (`session`, `lastFrame`) follow request key order, so replies are byte-different but equal.
