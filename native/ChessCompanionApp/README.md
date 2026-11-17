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

## Replay game mode — November 15, 2026

A second mode (segmented picker "Study position / Replay game", shown only when all 15 replay frames are bundled and match their pins). `ReplayGame.swift` holds `ReplayGameModel` and `ReplayGameView`; the state machine is documented at the top of that file. The app steps through the 14 frames of the selected sequence (1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6) plus an optional obstructed frame, reads each frame with the native recognizer, and after one complete five-box human review of the shown frame keeps the game with the bundled legal-move tracker (`ReplayTracker` over `ReplayTrackerRuntimeTransport`, same WebKit runtime as the engine). Each tracked position can be analyzed for a text recommendation; there is no speech in this mode.

Safety rules: no tracker or engine call before the review; recognition never fills in squares (unknown stays unknown, confidence 0); anything other than a clean advance (same position, or exactly one tracked legal ply, ready after 2 observations) revokes tracking and requires a renewed review, including unknown squares, skipped plies, ignored/reordered frames, tracker error replies and transport failures; edit, review change, reset, background, runtime stop and leaving the mode also revoke. A recommendation is bound to (run id, review epoch, tracker revision, FEN) and shown only while all four are current; every step revokes it first. Stepping cancels analysis and waits for it to end before any tracker request. Virtual replay time is a step counter (+100 ms per observation, restarting at 0 with each new runtime), never the wall clock, and is not shown as a capture age. `historyComplete:false` is respected: no repetition claims.

`prepare_app.py` adds `--replay-directory` (required with `--self-test`), pins all 15 frame SHA-256s (also pinned in `ReplayGame.swift`), bundles pixels only (never the sequence manifest or its `evaluatorTruth`), and compiles `ReplayTracker.swift`, `ReplayTrackerRuntimeTransport.swift` and `ReplayGame.swift`. `StudyResources` accepts the replay asset group; `LocalOfflineBackend` vends the tracker transport.

Checks (outputs in `/Users/alexmunzon/chess-builds/replay-mode-2026-11-15/`):
- `ReplayGameChecks.swift` (mocked tracker transport emulating the JS contract, holdable recognizer/engine/tracker replies, in-flight ledger): 21/21, 0 tracker/engine overlaps. Four deliberate model breakages in copies outside the repo each make it fail (`mutations/summary.txt`). Existing mock suite still 28/28.
- Self-test (`--chess-self-test`) now adds 6 replay checks after the 12 study checks, under a separate 240 s watchdog; review is the labelled scripted fixture. Simulator `746F2CEB…`: the 14-frame game tracked through real recognition and the real bundled tracker in every run, with legal text at plies 0–6 in the best run; obstruction gave tracker `needs-confirmation / uncertain-squares` (16 unknown squares) and blocked until renewed review; advancing during analysis showed nothing stale and the tracker request started only after the analysis ended. Some runs had engine search/startup deadline failures under heavy host load from other processes; these failed closed (no recommendation), but they fail the strict full-game check in those runs (see the report files).
- Unsigned arm64 device builds of both variants; the normal build contains no self-test symbols.

## Special-move game in Replay mode — November 15, 2026

Replay mode now has a "Game" picker with two bundled games: the unchanged 14-frame opening and the 26-frame special-move game (en passant, captures, promotion `cxd8=Q+`, both castlings) with two insertable interruptions (occlusion, missing piece). Choosing another game acts like Reset (revokes at once, stops the engine). Details, bundling and limits: `docs/SPECIAL_REPLAY.md`.

Build flag `--special-replay-directory <generator out>/pixels` (28 pinned PNGs under `ReplaySpecial/`; required together with `--replay-directory` for `--self-test`). The self-test adds 7 `special-*` checks and a `specialReplayGame` report section. Evidence and exact commands: `/Users/alexmunzon/chess-builds/special-replay-2026-11-15/`.

## Pre-started engine and a 100,000-node search — November 16, 2026

The bundled runtime now uses the pre-started engine (`src/core/prewarmed-engine.js`, see `docs/PREWARMED_ENGINE.md`) and every analysis searches a fixed 100,000 nodes (`LocalOfflineBackend.searchBudget = .nodes(100_000)`, see `docs/ENGINE_BUDGET.md`) instead of 1 second. The runtime bundle has 16 assets (`core/prewarmed-engine.js` added); `NativeEngineRuntime` allows exactly that one extra asset and exactly two extra engine command kinds, `prewarm` and `cancelPrewarm`. Neither command carries a position, and neither reply carries a move or text.

When the engine is pre-started:
- Study: when a complete board is read, when all five review boxes are ticked, and after a successful validation of a non-terminal position.
- Replay: when a complete frame needs review, when all five boxes are ticked, and when a review starts tracking.
- Never before the engine runs, never for a board with unknown squares, and never while a request of the same mode is in flight (the runtime runs one request at a time).

When the spare engine is dropped: un-ticking a review box, choosing another position or game, reset, backgrounding and leaving Replay (the last four also close the runtime, which ends every engine). Exception for un-ticking (2026-11-17): if another request is pending at that moment, the runtime refuses the cancel as busy and the app ignores the refusal; see the busy rule below. The spare only ever searches a fixed warm-up position; its result is thrown away, and an analysis accepts a `bestmove` only if it matches this search's own principal variation. A failing pre-start is silent: the analysis starts a fresh engine as before.

Analysis replies now carry diagnostic search facts (`search`: nodes, nodes per second, search time, start-up path `fresh`/`spare`/`fallback`, start-up wait). They are never used to decide advice; the Swift adapter accepts replies with or without them and checks the key set exactly when present.

Self-test (`--chess-self-test`): every analysis logs nodes, nodes per second, search time and start-up path, and the report has an `engineSearch` section. New checks: `prewarm-spare-serves-reviewed-position`, `untick-review-discards-spare`, `runtime-allowlist-refuses-unknown-asset-and-kind`, `replay-switch-game-during-analysis-real-engine` and `every-analysis-searched-node-budget-with-speed-reported` (30 checks in all). The three existing in-flight checks (study switch, replay advance, special-game occlusion) used to wait a fixed 200 ms after "Analyze"; a 100,000-node search on a pre-started engine can finish inside that, so they now wait until the analysis request has been sent, then 30 ms, and they fail if the request was never sent or had already been answered.

Follow-up after review (same day): the runtime has one pending-request slot shared by engine and Replay tracker requests, and a new request normally cancels the pending one. A delayed pre-start could therefore cancel a tracker request (failing safe, but revoking tracking). `NativeEngineRuntime.submit` now refuses a `prewarm`/`cancelPrewarm` while any other request is pending (`mayReplace`); real requests still supersede as before. Checks: `native/ChessCompanionIntegration/RuntimeGuardChecks.swift` (macOS, compiled with `NativeEngineRuntime.swift`; takes a runtime bundle directory), and a live case in the self-test check `runtime-allowlist-refuses-unknown-asset-and-kind` (a prewarm sent while a real analysis is pending is refused and the analysis is not cancelled).

Follow-up, 2026-11-17: `RuntimeGuardChecks` now also drives the real `submit` in a headless macOS WKWebView with the built bundle: a `prewarm` or `cancelPrewarm` sent while a real analysis or a well-formed Replay tracker request is pending must be refused as busy while the held request still gets its normal reply; with nothing pending both are accepted. A second runtime with the occupancy setting on checks the occupancy slot: a second tracker request while one is pending is refused as busy, tracker requests never cancel a pending analysis, and a stop supersedes a pending reading. 15 checks in all; 12 of 12 review mutants of `NativeEngineRuntime.swift` fail it (with the guard line removed: 11 of 15). Evidence: `/Users/alexmunzon/chess-builds/engine-leftovers-2026-11-17/` and `round2/`. It runs in `/Users/alexmunzon/chess-builds/special-replay-2026-11-15/mocks/run-all.sh`. Busy rule: `cancelPrewarm` stays refused while another request is pending, on purpose, because letting it through would go via `DeviceBackend.handle`, which cancels the running job first. What is left behind depends on what is pending. A pending analysis has already taken the spare, so nothing is left. A pending Replay tracker (or `position`/`move`) request has not, so a ready spare survives until the 60 s idle age, shutdown or the next analysis takes it (at most about 70 s). It holds no position and no advice comes back: an analysis still needs a confirmed, reviewed position and searches that position itself. The self-test case above now passes only when the held analysis replies; a timeout is recorded as `timed-out` with a message and is not a pass.

## Occupancy tracker plumbing, OFF by default — November 16, 2026

The bundled runtime now also carries the occupancy move tracker (`src/core/occupancy-tracker.js` and
`src/core/occupancy-move-inference.js`, copied unmodified; 18 runtime assets). It is **off by default** and the app has **no picture
source**: no camera, glasses or other feed produces board readings, so nothing in the app sends the tracker anything, and the
tracker never gives or keeps advice. Details and the open requirements: `docs/OCCUPANCY_TRACKER.md`, section "Wiring".

- Setting: the app keeps no stored settings, so it is a launch argument, `--occupancy-tracker-on`, read once per launch
  (`TrackerSetting.swift`) and passed to `NativeEngineRuntime(resourceDirectory:occupancyTracker:)`. Without it every tracker
  request (`trackerStart`, `trackerIngest`, `trackerSnapshot`, `trackerStop`, and since 2026-11-17 `trackerAnswerPromotion`) is refused with "Occupancy tracker disabled." and the
  app behaves as before. Nothing in the app sends tracker requests except the self-test; interruption handling (sending
  `trackerStop` on background, edit or reset) is a requirement for whoever connects a picture source.
- Tracker requests use their own pending slot in `NativeEngineRuntime`; they never cancel or delay an engine or Replay request,
  and the engine slot's rules (`engineKinds`, `trackerKinds`, `mayReplace`) are unchanged. Any tracker request that fails on the
  Swift side (busy, timed out, cancelled) revokes the page's tracker; `trackerStop` is never refused.
- Still open: hole (c) (the moving piece itself exchanged or replaced) and an exchange between two pictures with nothing hidden;
  occupancy alone cannot see either. Every requirement that needs a real picture source (one monotonic clock, 6 pictures per
  second, covered squares read unknown, polling every 100 ms and hiding advice older than 250 ms) is untested.
- Self-test: three new checks run after the special game: `occupancy-tracker-off-refuses-every-request` (through the app's own `LocalOfflineBackend`, setting as
  launched, so a hardcoded `true` in `AppAdapters.swift` fails it), `occupancy-tracker-on-honest-move-trusted` and `occupancy-tracker-on-hidden-swap-revoked` (a separate runtime created
  with the setting on; scripted SYNTHETIC readings; a real 100,000-node analysis is pending during the honest-move requests and must
  still reply). 33 checks in all.
- Promotion answer (2026-11-17): `trackerAnswerPromotion` carries the person's choice of piece when a pawn promotes (occupancy
  cannot see it). Same gates as the other kinds; a malformed or unknown-piece answer revokes; a late answer (after a stop, a new
  start or a newer reading) changes nothing; a different piece for an already answered question revokes; question ids carry
  a random per-page part, so an answer from before a reload never matches; an accepted answer still needs fresh readings before the tracker is ready. New
  self-test check `occupancy-tracker-on-honest-promotion-trusted` (34 checks in all; the setting-off check now also covers `trackerAnswerPromotion`): compiled, not yet run on the Simulator or phone.
- Results (Simulator `746F2CEB…`, evidence `/Users/alexmunzon/chess-builds/tracker-wiring-2026-11-16/round2/`): the three new
  checks passed in every round-2 run (4 of 4). Engine A/B against a build of the previous commit, 4 runs each, order alternated,
  each launched after the 1-minute load fell below 8 (one baseline run's load rose to 16.8 at launch): engine deadline failures
  5 of 100 analyses (changed) and 15 of 100 (baseline); the four launch fixture checks failed 0 of 16 and 4 of 16; existing checks
  passed 116 of 120 and 106 of 120. Round 1's runs on a busier host (load 20 to 48) showed the opposite imbalance; that one did not
  repeat here, so it is inferred to be host load. A copy whose `AppAdapters.swift` hardcoded `true` failed
  `occupancy-tracker-off-refuses-every-request` (1 of 1 run).
