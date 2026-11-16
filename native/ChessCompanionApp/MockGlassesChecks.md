# Mock-glasses checks (MockGlassesSource.swift)

Simulator-only; compiled with `prepare_app.py --simulator --mock-glasses` and run with launch argument
`--mock-glasses` (optional `--mock-glasses-stage app|configure|enable|pair|power|don|feed|session|stream|full`
stops after that step). Results go to the app's `Documents/mock-glasses-report.json` and up to 60 PNGs in
`Documents/mock-frames/`. Full results and commands: `docs/MOCK_GLASSES_RUN.md`. Entry: the mock file defines
`SelfTestHook`, attached by the shared `#if COMPANION_SELFTEST || COMPANION_MOCK_GLASSES` line in
`ChessCompanionApp.swift` (the two flags are mutually exclusive in `prepare_app.py`).

What the full run does:
1. Measurement stream (own `Camera`, raw/high/30 fps): logs each frame (arrival, PTS value/timescale, receipt
   uptime, pixel format, size, frame-index code read from the luma plane), 40 s steady, then doff, fold and
   power-off with their inverse actions; a new session and stream if the inverse alone does not resume.
2. Existing capture path: the real `CaptureCoordinator` with counting stubs (recognizer returns a complete
   starting-position proposal on purpose; engine, rules text and speech only count and throw), fed by
   `DATCaptureAdapter` (raw/medium/2 fps).
   - Gate probes (adapter path and a direct path that stops in strict order): stop acknowledged, full review,
     speech experiment on; `analyzeReviewedPosition` must refuse with `unknownCaptureAge`.
   - Revoke cycles for doff, fold, power-off and camera permission denied (mock permission API), plus denied
     before start: capture state sampled 1 s and 4 s after the event and 4 s after the inverse action alone.
3. `safety` (pass/fail): every frame that reached the coordinator `.unknownDAT` (measurement-stream frames are
   logged only and counted separately in `safetyInputs`); no permit possible (engine and speech-text stubs never
   called; the coordinator has no permit counter); no recommendation in a 50 ms poll; 0 speech requests; no analysis;
   gate refused for unknown capture age. `revokeAssertions` per event. `negativeControl`: each of the six checks is
   re-run on a mutated copy of its inputs and must turn false (`negativeControlAllTurnFalse`).
4. After the direct gate probe the same camera's stream is restarted; the mock refuses that restart, so the review
   persists and the refusal stays `unknownCaptureAge` (recorded as `afterResume`).

Never used: `setCameraFeed(cameraFacing:)`, microphone, audio session, speech, registration or permission requests.
