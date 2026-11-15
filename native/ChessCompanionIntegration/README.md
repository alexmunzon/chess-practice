# Phone-local integration adapters

This small module connects the existing Swift capture contracts, native synthetic vision and local engine runtime. The application runtime is intended to stay entirely on the iPhone. A Mac is used here only to compile and run development checks; there is no Mac server or remote inference endpoint.

`SyntheticFrameRecognizer` implements `FrameRecognizer` using `NativeSyntheticRecognizer`. It verifies the frame byte hash, passes **only image bytes** to recognition, checks the fixed implementation/template identity and returns an unreviewed `BoardProposal`. Unknown cells stay unknown. It accepts **trusted prerecorded replay frames only** and rejects DAT frames before inference. This explicit boundary prevents the synthetic marker/template baseline from being presented as physical chess recognition. It does not manufacture FEN or historical state.

`LocalChessAdapters` implements both `LocalChessRules` and `NativeChessEngine` using one injected JSON transport. Full six-field FEN is mandatory. Each new request revokes the prior operation before validating its input; already-cancelled old tasks cannot revoke newer work. Frame epoch, sequence and review revision must be within JavaScript's exact integer range, **0…2^53−1**, with positive epoch/revision. Booleans and fractional/unsafe values cannot pass as integers. Replies must match the request envelope, original full FEN, frame identity and canonical UCI fields. The move-verification response must echo the original FEN and checked move before its regenerated speech text is accepted.

`NativeRuntimeTransport` is the concrete wrapper around `NativeEngineRuntime`. Cancellation is scoped to a fresh operation UUID, separate from the analysis request ID. It cancels its own submission task, whose runtime cancellation handler checks the private transport ID; it never calls the runtime-wide cancel method. A delayed cancellation/completion cannot cancel a replacement request, including one from another wrapper. The local package graph includes Capture, Vision and Runtime by filesystem path only; no remote dependency resolution is introduced.

`SyntheticPhoneServices` merely constructs these adapters. It does not start WebKit, register with Meta, request device permission, connect a camera, confirm a board or speak. The host app explicitly constructs and starts its local runtime, supplies the template asset bytes, and supplies a speech sink when creating its capture coordinator. Human review remains an independent app/UI operation; this module supplies no default review/history flags.

```swift
// runtime is explicitly constructed/started by the host app in an authorized flow.
let transport = NativeRuntimeTransport(runtime: runtime)
let services = try SyntheticPhoneServices(templateData: bundledTemplateBytes, transport: transport)
let coordinator = try CaptureCoordinator(
    recognizer: services.recognizer,
    engine: services.chess,
    rules: services.chess,
    speech: userControlledSpeechSink
)
// Still dormant: no connect, capture, review, analysis or speech call above.
```

## Verification scope

The standalone Swift checks use a mock JSON transport and never create or execute a WebKit instance. Thirteen checks passed: dormant construction, full FEN/history, safe integer boundaries, malformed replies/UCI, move echo, cancellation races, invalid new input revoking old analysis, unknown synthetic proposals, rejection of DAT frames before model inference, and the concrete transport wrapper's task-scoped cancellation across two wrappers and pre-cancelled calls. The latter tests substitute a runtime stub at compilation; they do not execute WebKit.

One check replays **actual current `DeviceBackend` JSON** generated under Node on the development Mac using the real pinned Stockfish engine with a 100 ms bounded search. The fixture contains position validation, its actual best move, and legal move/speech output. The Swift transport changes only `requestId` and the analysis identity to bind each test invocation; FEN, move, successor position, status and speech stay unchanged. This validates the JavaScript→Swift schema, not WebKit/iPhone runtime compatibility. The remaining lifecycle cases use explicit mocks. The template asset is loaded to test the DAT rejection gate; no model inference runs in this test suite.

The combined sources typecheck for arm64 iOS17.2 using the installed iOS26.2 SDK, including the concrete `NativeEngineRuntime` and `NativeRuntimeTransport`. No WebKit, device, audio, browser or permission operation is part of that compiler check. The package dependency graph is source configuration; SwiftPM execution remains unverified in this sandbox.

Direct checks are run from the repository root with package-local caches. Compile the capture contracts, vision sources, `Adapters.swift`, `RuntimeTransport.swift` and `IntegrationChecks.swift` together using `-D COMPANION_MONOLITHIC_BUILD -D COMPANION_RUNTIME_SOURCE -D INTEGRATION_TRANSPORT_STUB`, then pass the frozen `device-backend-fixtures.json` path to the executable. The iOS typecheck uses the actual `NativeEngineRuntime.swift` plus `CaptureCoordinator.swift`, and omits the test file and stub flag. Exact executed commands, logs, fixture provenance and source hashes are saved in the continuation chat's `outputs/native-readiness-2026-11-11/integration/` evidence folder.

This is working source integration, not a completed iPhone app. Real physical-board recognition, reviewed UI, validated DAT capture timestamps, WebKit Worker/WASM compatibility, deployment and glasses/audio behavior remain separate gates. DAT capture age remains unknown in the capture coordinator, so live DAT engine/speech permits remain blocked.
