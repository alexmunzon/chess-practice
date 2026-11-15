# Offline iPhone study app

## Simulator follow-up — November 13, 2026

All four playable fixtures have now completed the actual Simulator recognition → explicit FEN review → validation → analysis flow. Promotion returned legal `e1e2` (“king from e1 to e2”), separately rules/text checked; earlier moves were `e2e4`, `c7c5`, `e1d2`. The obstructed board exposed 16 unknown squares and blocked advice. Actual UI checks also passed for invalid rules-state FEN with matching pieces (side-to-move `x`), background/foreground review and recommendation invalidation, and reset after backgrounding. A rapid Analyze → Home sequence completed its UI actions within 290 ms; returning showed no stale recommendation and unchecked review. This does not prove exact engine receipt time or delivery of a late callback.

No app source changed in this follow-up; current source and signed artifact hashes match the prior build. A freshly compiled standalone mock lifecycle suite passed 10/10, including held analysis reply after a position switch. Prior 172/172 Node regression remains applicable to the hash-matched source and was not needlessly repeated.

Remaining strict acceptance limit: exact in-flight position-switch timing could not be reliably observed through CUA navigation within the one-second search. Keep the held-reply mock evidence distinct from actual Simulator execution; do not claim the full strict checklist is complete. No new runtime failure or code defect was found. Local Simulator approval is already granted and remains valid for the same scope. No physical phone, glasses, capture-age or audible-output validation, commit, push or distribution occurred.

Current evidence and quickstart: `/Users/alexmunzon/Documents/Codex/2026-11-12/task/outputs/chess-simulator-followup-2026-11-13/` (`results.json`, `identity.json`, `promotion-rules-check.json`, `mock-lifecycle.json`, `Quickstart-and-results.md`). Historical evidence remains untouched in the adjacent `chess-simulator-runtime/` folder.


## Latest Simulator checkpoint — November 12, 2026

The local iPhone 17 / iOS 26.2 Simulator test is now explicitly approved. The app was ad hoc signed, strictly verified, installed and launched on the existing Simulator. Actual UI flows produced `e2e4` from the starting position, `c7c5` after 1. e4 and `e1d2` from the en passant fixture. Each visible text matched a separate Node rules/text check. Four-of-five review blocked validation; unchecking a review revoked the recommendation; incomplete FEN was rejected. Promotion recognition and sample FEN loading passed, but promotion analysis remains untested.

One UI fix makes each recognized square a single labelled accessibility element; duplicate child labels disappeared in the Simulator. The full Node suite passed 172/172 after the change; the updated Simulator build compiled, signed and passed strict signature verification. Independent read-only review found no remaining concrete code issue. Native scroll/drag repeatedly failed with CUA `noWindowsAvailable`; exposed AX Scroll Up/Down actions worked intermittently, including after rotation to landscape. The last screenshot call was aborted by the user, so UI interaction paused without retry. This is a partial actual-Simulator checkpoint, not a completed offline acceptance milestone.

Remaining actual UI checks: promotion review/analysis, obstructed-board blocking, invalid rules-state FEN with matching placement, reset, background/foreground invalidation and in-flight switching/late completion. Existing mock evidence for these lifecycle gates remains distinct. No physical phone, glasses or audible output validation occurred. The existing local Simulator approval remains valid; no further permission is pending for these same tests. Preserve all prior work, the original unsigned artifact and consumed Mac approvals. No commit, push or distribution occurred.

Exact current evidence, commands, source/artifact hashes, observed outputs and limitations: `/Users/alexmunzon/Documents/Codex/2026-11-12/task/outputs/chess-simulator-runtime/` (`runtime-journal.json`, `rebuild-report.json`, `rebuild-signing.json`, `observed-move-checks.json`, `npm-test.txt`, `independent-review.md`). The signed updated build is at `/private/var/folders/40/pkx1ymn10_s42501bl5799wh0000gn/T/chess-accessibility-build-x711t4_3/build/ChessCompanion.app`; bundle ID `local.chesscompanion.offlinestudy.simulator`; destination UDID `746F2CEB-102D-4CFC-8D11-A5924705537F`.

Earlier sections below preserve historical build and Mac evidence. The Simulator is no longer compile-only, and the old Mac timeout investigation is resolved.


This is a small SwiftUI app assembly for **offline synthetic study** on the iPhone. It uses the native pixel recognizer and bundled local rules/Stockfish, then requires complete human review before analysis or an explicit speech request. The Mac is a build/test host only.

The app has no Meta registration, camera, microphone or Bluetooth flow. Live glasses mode is visibly unavailable. It does not assign a capture timestamp to the saved image, use `CaptureCoordinator.submitReplay` as a freshness workaround, or modify the live one-second guard. Offline study deliberately permits a person to review an old image at their own pace. New input, review changes, reset, backgrounding and view disappearance revoke output and synchronously stop speech.

## Multi-position iPhone Simulator study

The Simulator build includes four known synthetic positions and one obstructed board. Choose a position, start the engine, then choose **Read board**. Inspect the image and proposed squares. For a complete board, enter a six-field FEN or choose **Use sample FEN**, confirm all five review fields, validate, and analyze. The sample only fills the editable draft. Switching positions clears the previous image, review, FEN and recommendation. The obstructed board demonstrates uncertainty blocking. Simulator recommendations are text only.

Build with the pinned local assets and the existing synthetic corpus's `pixels/` directory:

```sh
python3 -B native/ChessCompanionApp/prepare_app.py --simulator \
  --out /absolute/new/private-output \
  --runtime-assets /absolute/prepared/local-runtime-assets \
  --fixture /absolute/corpus/pixels/000000.png \
  --fixture-directory /absolute/corpus/pixels
```

The command compiles an unsigned arm64 iOS Simulator bundle. Local ad hoc signing, installation and execution are separate steps. The four additional PNGs are pinned by SHA-256. The original single-position device build command still works.

## Current source flow

1. **Start local engine** explicitly creates/starts the isolated local runtime. App/model construction starts no WebKit, recognition, SDK or speech operation.
2. **Recognize bundled image** passes only the owned image bytes to the native synthetic recognizer. The image and all 64 proposed squares remain visible. Unknown cells block validation.
3. Enter a complete six-field FEN or explicitly load the sample draft. Review each historical field; all five review checkboxes start unchecked. The entered piece placement must exactly match every recognized square before local chess rules validate it.
4. **Analyze offline position** binds engine and regenerated legal speech text to the image hash, reviewed FEN, revision and request identity. Late replies cannot restore results after changes.
5. **Speak offline move** uses an already-installed English voice only after a separate explicit action. The UI reports that speech was requested, not that it was heard. No audio session/route is changed. Actual speech and glasses routing remain untested.

The fixed owned fixture is the generated starting image from the existing simulation corpus, SHA-256 `ed30d4974c39e73d64c5450a1bc1ea66359e7241e28cc5f88d6bd0299207926a`. It is copied into private build output, not embedded as base64 or replaced with labels. For this separately documented known-new-game fixture, the complete state is:

```text
rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1
```

This FEN is a review reference only. It is never an input to recognition and is not automatically filled or confirmed by the app. Earlier repetition history remains unknown.

## Private unsigned assembly

Use already prepared local runtime assets from `scripts/build-device-runtime.mjs`, the recorded owned fixture, and a **new output directory outside the repository**:

```sh
python3 -B native/ChessCompanionApp/prepare_app.py \
  --out /absolute/new/private-output \
  --runtime-assets /absolute/prepared/local-runtime-assets \
  --fixture /absolute/path/to/000000.png
```

The assembler verifies installed and locked dependency versions, every runtime asset against its current pinned local source, asset MIME/length/hash, the exact fixture, and local template bytes. It snapshots the exact Swift source bytes into the output and compiles those snapshots with the installed iOS SDK, target arm64 iOS 17.2, Swift 6 and explicit `-no_adhoc_codesign`. No SDK/package download, Xcode destination selection, SwiftPM sandbox bypass, account, signing, installation or execution occurs. It preserves engine/rules license notices and checks that the resulting Mach-O has no `LC_CODE_SIGNATURE`.

The private `.app` is **unsigned and not installable as delivered**. Provisioning/signing and device launch are separate authorized work. Do not distribute the engine bundle until GPL corresponding-source delivery obligations have been verified.

## Verified checkpoint

- Eight standalone mocked controller checks passed: dormant construction, explicit review/speech, mismatched or unknown pixels, late recognition/validation/analysis, invalid replies, background/reset and old-start completion isolation. No WebKit, recognition inference, device or audio execution occurred in these checks.
- The full app sources compiled and linked to an unsigned arm64 iOS executable using the installed iOS 26.2 SDK. The private resource bundle assembled successfully and no code signature was present.
- An initial full compile hit a Swift 6.2.4 IR-generation crash on implicit actor-isolated method references in SwiftUI callbacks. Replacing those references with explicit closures produced the successful second build. Both logs remain preserved; no compiler upgrade or permissions change was used.
- App launch, layout/accessibility interaction, bundle loading on iPhone, iPhone app pipeline execution, iPhone performance and audible output have **not** been tested. This is a build checkpoint, not a live glasses implementation.

The monolithic build deliberately includes the shared Capture contracts, Vision, Runtime and Integration source files with `COMPANION_MONOLITHIC_BUILD` and `COMPANION_RUNTIME_SOURCE`; it excludes SDK capture adapters and all standalone `@main` test harnesses. The controller uses frame identity solely to bind offline analysis, with no live timestamp or speech permit.

Evidence is under the continuation chat's `outputs/native-readiness-2026-11-11/app/`. The unsigned binary, bundled WASM and exact source snapshots stay under `work/iphone-offline-app-v2/`.

## Composed Mac checkpoint — November 12, 2026

The app adapter's native confidence contract was corrected from `Double` to exactly `Int(0/1)` and rebuilt earlier. The resumed Mac check now reaches real synthetic recognition and full review validation: all 64 positive cells agree, and the occluded fixture preserves 16 unknowns. A diagnostic run then timed out at its first native analysis request after about 15.01 seconds, before any legal-text or text-sink call. The Worker/JS cause is unknown; all production deadlines and gates remain unchanged. No iPhone app was launched.

`VerifyComposedStudy.swift` now uses evaluation-only `ComposedStudyDiagnostics.swift`; compile it with the helper, excluding the separate `ComposedStudyDiagnosticsChecks.swift` entry point. Pure diagnostics passed 17/17; project Node regression passed 172/172. Both Mac run approvals are consumed. Exact commands, hashes, failed results and the queued next task are in [the latest checkpoint](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/STATUS.md) and `HANDOFF.md`.

## Integration with the 15-asset runtime — November 15, 2026

`prepare_app.py` now pins `core/observation.js`, `core/device-game-session.js` and `core/replay-runtime.js` (15 runtime assets, same source/hash strictness; no ReplayTracker Swift sources in the app yet). `NativeEngineRuntime` gained `onClose`, fired once on the first close/failure; `LocalOfflineBackend` wires it to `runtimeStopped()` so the model's closed signal is immediate (explicit `close()` clears the handler first). The self-test probe forwards `observeClosure` to the real backend and logs `backend.closed`.

Checks (outputs in `/Users/alexmunzon/chess-builds/integration-2026-11-15/`): mock suite 28/28; normal and self-test Simulator builds compile (normal build has no self-test strings); ad hoc signed self-test build on Simulator `746F2CEB…` passed 12/12, complete, 0 speak requests, in 3 of 3 runs (first real-WebKit execution of the 15-asset bundle; analysis 1.7–4.1 s, engine start 0.9–2.0 s); unsigned arm64 device builds of both variants; `npm test` 184 pass, 0 fail, 2 skipped. Nothing was installed on the phone.
