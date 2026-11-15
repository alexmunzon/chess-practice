# Replay game: JavaScript tracker contract (frozen, schemaVersion 1)
`src/core/replay-runtime.js` (`ReplayRuntime`) owns one `DeviceGameSession` and exposes it through
`handle(requestJSON) -> replyJSON`, synchronously. It tracks a game across replayed frames only. It
runs no engine, speech, HTTP or device API, and is not yet bundled into the phone runtime.

## Requests

Every request: `schemaVersion:1`, `requestId` (`[A-Za-z0-9_.:/-]{1,128}`), `kind`,
`mode:"trusted-replay"`, `clockDomain:"replay-synthetic-v1"`, plus exactly these keys:

| kind | extra keys |
|---|---|
| `initialize` | `session{sessionId,epoch>=1}`, `fen` (complete six-field, human-reviewed), `reviewed{pieces,turn,castling,enPassant,counters}` all `true` |
| `observe` | `frame{identity{sessionId,epoch,sequence>=0,frameSha256 (64 hex)}, capturedAtMs>=0, squares}`; `squares` has all 64 squares, each `{label, confidence 0..1}`, label in `empty`, `unknown`, `PNBRQKpnbrqk` |
| `invalidate` | `session`, `reason` in `manual-edit`, `interrupted`, `background`, `reset`, `disconnect` |
| `snapshot` | `session` |

Any other kind (including engine kinds such as `analyze`, `validate`, `position`, `move`, `cancel`),
any missing or extra key, or a wrong mode, clock domain or schema version is rejected.

## Replies

Success, exact keys in this order: `schemaVersion`, `requestId`, `kind`, `runtime:"on-device-local"`,
`mode:"replay-only"`, `session`, `lastFrame` (`{sessionId,epoch,sequence,frameSha256,capturedAtMs}` or
null), `trackingReady`, `guidanceAllowed:false`, `liveGuidanceAllowed:false`,
`state{status,reason,revision,fen,lastMove,historyComplete:false}`, and optional `ignored`
(`repeated-or-reordered-frame` or `before-confirmation`; the tracker did not change).

Error, exact keys: `schemaVersion`, `requestId` (null if unreadable), `kind` (null unless one of the
four kinds), `runtime`, `mode`, `guidanceAllowed:false`, `liveGuidanceAllowed:false`,
`error{code,message,trackerRevoked}`. `trackerRevoked:true` means the tracker revoked tracking (it
does so on every rejected request); a new full human review (`initialize`) is needed.
`STALE_SESSION` (`trackerRevoked:false`) means a frame or command named a foreign or retired
session; the tracker ignored it and stayed unchanged.

`trackingReady` only means a stable legal position; never permission to advise, speak or analyze.

## Tracker rules the replay inherits (not changed here)

- Readiness needs two matching frames at least 50 ms apart; each new legal position must be seen
  the same way before `trackingReady` is true again.
- Zero or one legal ply per position change. A skipped ply, ambiguity, an `unknown` square, or any
  confidence below 0.95 revokes until `initialize`.
- Frames older than the last accepted sequence or time are ignored. Reusing the latest sequence
  with a different hash or time is `FRAME_IDENTITY_CONFLICT` and revokes.
- More than 1000 ms of virtual time without an accepted frame revokes (`observation-timeout`).

## Virtual clock

Starts at 0; becomes `max(previous, frame.capturedAtMs)` only for frames of the active session, and
only after the tracker has validated the request. Other kinds never move it. The module never reads
a host clock. Start a replay with first frames at `capturedAtMs <= 1000`, because `initialize` is
stamped at the current virtual time.

## Pacing rule

Tracker requests and engine requests are never concurrent. The replay host sends one request,
waits for its reply, then sends the next. Engine analysis, when a later packet adds it, runs only
between tracker requests, on a FEN the tracker reported, and is cancelled before the next tracker
request.

## Deviations and limits

Dropped tracker reply fields `invalidationReason` and `clockDomain` (exact key list; the reason is in
the request). A foreign session is an error reply, but the tracker does not revoke on it (its rule).

Synthetic observations only (labels built from FEN by chess.js); no recognizer, camera or real
frame timing is validated. Golden transcript: `tests/fixtures/replay-runtime/transcript.json`;
regenerate with `UPDATE_REPLAY_FIXTURE=1 node --test tests/replay-runtime.test.js`.

## Phone runtime wiring (2026-11-15)

The tracker is now inside the phone's local WebKit bundle. `scripts/build-device-runtime.mjs` copies
`core/observation.js`, `core/device-game-session.js` and `core/replay-runtime.js` unmodified (15
hashed assets, was 12). `native/ChessCompanionRuntime/runtime.js` builds one `ReplayRuntime` next to
the engine backend and routes with its exported `createRequestRouter`:

- A request whose `kind` is one of the four tracker kinds, or which claims `mode:"trusted-replay"`,
  goes only to the tracker (which rejects and revokes on anything outside this contract, as in
  golden step 27). Everything else goes to `DeviceBackend` exactly as before.
- A tracker request first cancels any engine analysis, then runs synchronously; the native host also
  keeps one pending request, so the two never overlap. A superseded analysis rejects, never replies.
- Tracker replies (including structured errors) are posted as `ok:true` results so the Swift decoder
  sees the error code.

`NativeEngineRuntime.swift` accepts the four tracker kinds only with `mode:"trusted-replay"`, rejects
any engine kind that carries `mode`, serves the three new assets, and additionally requires tracker
replies to be `mode:"replay-only"` with boolean-false `guidanceAllowed`/`liveGuidanceAllowed`.
Engine reply checks are unchanged. `ReplayTrackerRuntimeTransport.swift` adapts any
`LocalJSONTransport` (or `NativeEngineRuntime` via `NativeRuntimeTransport`) to
`ReplayTrackerTransport`, with a fresh operation UUID per request.

Evidence: `tests/replay-runtime-bundle.test.js` imports the built bundle and replays the golden
transcript through the router (28/28 byte-identical); 5 new mocked IntegrationChecks (18/18 total).
Outputs in `/Users/alexmunzon/chess-builds/replay-wiring-2026-11-15/`. **Not verified:** no WebKit,
Simulator or device execution of the new bundle at that time; `VerifyRuntime` (now also sends initialize
and snapshot) was compiled only. Since then the app build (`native/ChessCompanionApp/prepare_app.py`) pins
all 15 runtime assets, and the Replay game mode runs this bundle in the Simulator self-test.

Virtual time and sequences are whole safe integers: `capturedAtMs` must pass `Number.isSafeInteger`
(a value such as `1e300` or `100.5` is rejected, revokes tracking and never moves the virtual clock).
