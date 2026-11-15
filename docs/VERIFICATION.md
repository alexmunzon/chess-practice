# Current verification — November 12, 2026

## Actual iPhone installation and opening — November 15, 2026

The staged kit completed. Actual iPhone17/iOS27.2 installation is confirmed by device inventory; launch was accepted after user-confirmed developer trust, and Alex confirmed the app opens and stays open. He then closed/swiped it away. Profile/app checks passed 40/40 and signed-product checks 29/29. Exact signed and original unsigned artifacts, separate failed/successful logs and limits are at `/Users/alexmunzon/chess-builds/iphone-2026-11-15/`. See `docs/PHONE_INSTALLATION.md`. Physical-phone recognition/engine UI acceptance and performance are still untested; no glasses or audible-output result is claimed.


## Private phone build preparation — November 13, 2026

Alex reconfirmed the reported phone as **iPhone 17 / iOS 27.2** on November 13. This remains user-reported, not physically queried. The unchanged Simulator-tested source compiled and linked successfully as a private unsigned arm64 iOS device app with all five study fixtures, using the installed iPhoneOS 26.2 SDK path supplied to Swift and deployment target 17.2. The Mach-O itself encodes minimum OS 17.2 and SDK 17.2; both observed facts are retained without assigning a cause. All 46 artifact checks passed. The unsigned executable SHA-256 is `43a02cdeed2143bec10fa06afd8d456efb76583ec6c806616a7a2f607edbbdb6`; bundle ID `local.chesscompanion.offlinestudy`. Actual iOS 27.2 compatibility and phone performance remain unverified.

Evidence and exact prepared artifact: `/Users/alexmunzon/Documents/Codex/2026-11-12/task/outputs/iphone-offline-preparation-2026-11-13/` (`Phone-build.md`, `build-report.json`, `verification.json`). Prepared unsigned app: `/private/var/folders/40/pkx1ymn10_s42501bl5799wh0000gn/T/chess-iphone-study-ruo4lyj9/build/ChessCompanion.app`. No app source changed. No signing identity, profile, account or physical-device inventory was queried; no signing, installation, launch, audio or glasses operation occurred.

Physical-phone approval is still required to inspect the actual connected target/existing signing setup, sign using an existing configured identity/profile if available, install, launch and exercise this private app with text-only output. Stop for new accounts, registration, credential entry, spending or permanent settings changes. Simulator approval does not cover physical-device actions. Do not invent a device ID, team, identity, profile or successful compatibility result. The separate actual-UI in-flight fixture-switch timing limit remains documented; its mock passed 10/10.


## Simulator follow-up — November 13, 2026

All four playable fixtures have now completed the actual Simulator recognition → explicit FEN review → validation → analysis flow. Promotion returned legal `e1e2` (“king from e1 to e2”), separately rules/text checked; earlier moves were `e2e4`, `c7c5`, `e1d2`. The obstructed board exposed 16 unknown squares and blocked advice. Actual UI checks also passed for invalid rules-state FEN with matching pieces (side-to-move `x`), background/foreground review and recommendation invalidation, and reset after backgrounding. A rapid Analyze → Home sequence completed its UI actions within 290 ms; returning showed no stale recommendation and unchecked review. This does not prove exact engine receipt time or delivery of a late callback.

No app source changed in this follow-up; current source and signed artifact hashes match the prior build. A freshly compiled standalone mock lifecycle suite passed 10/10, including held analysis reply after a position switch. Prior 172/172 Node regression remains applicable to the hash-matched source and was not needlessly repeated.

Remaining strict acceptance limit: exact in-flight position-switch timing could not be reliably observed through CUA navigation within the one-second search. Keep the held-reply mock evidence distinct from actual Simulator execution; do not claim the full strict checklist is complete. No new runtime failure or code defect was found. Local Simulator approval is already granted and remains valid for the same scope. No physical phone, glasses, capture-age or audible-output validation, commit, push or distribution occurred.

Current evidence and quickstart: `/Users/alexmunzon/Documents/Codex/2026-11-12/task/outputs/chess-simulator-followup-2026-11-13/` (`results.json`, `identity.json`, `promotion-rules-check.json`, `mock-lifecycle.json`, `Quickstart-and-results.md`). Historical evidence remains untouched in the adjacent `chess-simulator-runtime/` folder.


## Approved Simulator UI checkpoint — partial

The local iPhone 17 / iOS 26.2 Simulator test is now explicitly approved. The app was ad hoc signed, strictly verified, installed and launched on the existing Simulator. Actual UI flows produced `e2e4` from the starting position, `c7c5` after 1. e4 and `e1d2` from the en passant fixture. Each visible text matched a separate Node rules/text check. Four-of-five review blocked validation; unchecking a review revoked the recommendation; incomplete FEN was rejected. Promotion recognition and sample FEN loading passed, but promotion analysis remains untested.

One UI fix makes each recognized square a single labelled accessibility element; duplicate child labels disappeared in the Simulator. The full Node suite passed 172/172 after the change; the updated Simulator build compiled, signed and passed strict signature verification. Independent read-only review found no remaining concrete code issue. Native scroll/drag repeatedly failed with CUA `noWindowsAvailable`; exposed AX Scroll Up/Down actions worked intermittently, including after rotation to landscape. The last screenshot call was aborted by the user, so UI interaction paused without retry. This is a partial actual-Simulator checkpoint, not a completed offline acceptance milestone.

Remaining actual UI checks: promotion review/analysis, obstructed-board blocking, invalid rules-state FEN with matching placement, reset, background/foreground invalidation and in-flight switching/late completion. Existing mock evidence for these lifecycle gates remains distinct. No physical phone, glasses or audible output validation occurred. The existing local Simulator approval remains valid; no further permission is pending for these same tests. Preserve all prior work, the original unsigned artifact and consumed Mac approvals. No commit, push or distribution occurred.

Exact current evidence, commands, source/artifact hashes, observed outputs and limitations: `/Users/alexmunzon/Documents/Codex/2026-11-12/task/outputs/chess-simulator-runtime/` (`runtime-journal.json`, `rebuild-report.json`, `rebuild-signing.json`, `observed-move-checks.json`, `npm-test.txt`, `independent-review.md`). The signed updated build is at `/private/var/folders/40/pkx1ymn10_s42501bl5799wh0000gn/T/chess-accessibility-build-x711t4_3/build/ChessCompanion.app`; bundle ID `local.chesscompanion.offlinestudy.simulator`; destination UDID `746F2CEB-102D-4CFC-8D11-A5924705537F`.


## Composed Mac fix and multi-position Simulator build

The composed Mac harness passed after disabling inactive scheduling for the detached WebKit engine. Three 1,000 ms real Stockfish searches completed, as did three separate legal-text checks. Occlusion, incomplete and mismatched review, edit, reset and late completion after backgrounding passed. The first move was `e2e4`, and the harness used a text-only sink. [Full Mac result](/Users/alexmunzon/Documents/Codex/2026-11-12/continue-my-chess-project-using-the/outputs/Composed-Mac-Result.json).

An unsigned arm64 iOS Simulator build now bundles four playable positions plus an obstructed board. All 172 Node tests passed. All ten mocked lifecycle cases passed, including a held engine reply after position switching. Mac pixel checks matched each playable image's 64-square reference and preserved 16 unknowns for the obstructed board. Mac asset checks rejected partial and extra manifests and a tampered fixture. Separately, the Node worker produced a rules-checked recommendation for all four playable positions. Simulator signing, installation, launch and interaction are pending. No physical iPhone, glasses or audio test ran. [Build and exact source hashes](/Users/alexmunzon/Documents/Codex/2026-11-12/continue-my-chess-project-using-the/outputs/Simulator-Build-Evidence.json).

## Mac page timers, Worker output and cancellation

One Mac run at the existing deadlines sampled one `infoString` and seven `infoDepth` messages after Go. The 100 ms page probe fired on schedule by the page clock. The frozen trace recorded neither the 1,000 ms probe nor the 2,500 ms search timer, and it contained no Worker error or best move. The native timeout, Swift cancellation dispatch and JavaScript Worker abort signal carried the same request ID. The trace ended before an analysis reply arrived, so the failed reply code was unavailable. The 11 recognition and review assertions passed. No legal text or output was produced. [Execution record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-timer-trace-2026-11-12/execution.json).

Seven simulated Worker cases exercised classification, sampling limits, timer delivery and error codes. All 172 Node tests passed. Independent review checked both the prepared Mac build and the result. [Checkpoint](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-timer-trace-2026-11-12/STATUS.md).

## Mac search command, Worker callback and timer

One Mac evaluation at the existing deadlines verified that posting `go movetime 1000` returned and the page received a Worker message callback 3 ms later by its clock. The trace does not capture that message's contents. The report contains no Worker error, JavaScript search timer, or best move marker. Swift's timer expired 15,007.84 ms after dispatch. JavaScript finish then appeared and a failed reply reached Swift 5.09 ms after the native timer marker. The order is consistent with cancellation following the native deadline. The late reply's error code and the reason for the absent JavaScript timer marker remain unknown. Synthetic recognition and FEN validation passed, with zero legal-text or text-sink calls. [Execution record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-search-trace-2026-11-12/execution.json), [raw Mac report](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-search-trace-2026-11-12/mac-run.stdout.json).

Five simulated Worker cases verified the new markers and reply routing. The full Node suite passed 172/172. The trace remains Mac evaluation evidence, and the prior unsigned build remains the extent of iPhone verification. [Checkpoint](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-search-trace-2026-11-12/STATUS.md).

## Mac dispatch and Worker trace

The offline synthetic image and complete FEN review assertions passed again. The position validation reply reached Swift. For the first analysis, Swift dispatched the request, JavaScript received it, the Worker constructor returned, and Stockfish answered `uciok` and `readyok`. JavaScript recorded the attempt to post `go movetime 1000`. The native timer fired 13,957.02 ms after receipt of that marker. The captured trace has no best move, engine completion or failure, JavaScript analysis reply, legal-text call or text-sink call. The Mac process exited 1 after 24,662.15 ms. [Execution record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-trace-2026-11-12/execution.json).

The Go marker precedes the call to `postMessage`. The present trace cannot establish whether that call returned, a later Worker event arrived, the JavaScript timer ran, or engine cleanup began. The focused Node simulation verified trace ordering and per-request correlation. The full Node suite passed 172/172. Independent review verified the generated sources and assets and checked the interpretation of the run. The existing unsigned iOS artifact retains its prior compile-only evidence. [Trace checkpoint](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-trace-2026-11-12/STATUS.md).

## Composed offline study — recognition/review pass; first analysis times out

The corrected adapter and saved builds were hash-verified before one approved Mac run. It failed in 21,932.40 ms with a generic native deadline error; that report cannot distinguish the analysis/text-check cycle or operation. The original generic result remains unchanged. [Execution](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/execution.json).

A narrow evaluation-only diagnostic change preserves all nine production sources, original calls/predicates and deadlines. Foundation-only checks passed **17/17** and independent source review found no remaining concrete issue. The diagnostic harness compiled cleanly from 11 exact snapshots. A separately approved run exited 1 in **21,536.72 ms**: **firstAnalysis**, analyze ordinal 1, expired after **15,010.27 ms**. There were zero completed analyses, legal-text calls or text-sink calls; stderr was empty. Initial automatic permission review timed out before dispatch; the tool-permitted retry launched exactly one process. [Diagnostic preparation](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/diagnostics/preparation.json), [execution and trace](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/diagnostics/execution.json).

Eleven assertions passed: pinned synthetic inputs/runtime manifest, local asset readiness, the expected 16 unknown squares and blocking, exact 64-cell agreement with a separate frozen reference/FEN, no inferred review fields, incomplete/mismatched-review rejection and full reviewed FEN validation. This verifies the corrected integer-confidence path for these two synthetic images. Review is scripted ground truth, not live human confirmation. Worker creation, UCI readiness, actual search and JS/native reply progress remain unobserved. No Stockfish result, explicit output, edit/reset or delayed-background acceptance was reached in this run. No cause or need to increase deadlines is established.

The same 1,000 ms searches plus separate legal-text checks passed twice under Node in **1,467.15 / 1,361.74 ms**. That is a separate-runtime comparator, not a WebKit explanation. The required full Node suite passed **172/172** with the existing loopback authorization. [Comparator](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/node-budget-probe.json), [regression](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/npm-tests.txt), [independent review](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/review.md).

The earlier 3.91-second composed failure at occluded-image recognition and its native Int/Double correction remain preserved in [the prior record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/composed-study/execution.json). The corrected iOS artifact is still unsigned and was read as a resource directory only. No iPhone/simulator/glasses/camera/audio execution occurred. The next bounded dispatch/Worker trace is queued in HANDOFF.md; no automatic retry is running.

## Native preparation — current bounded evidence

The user-selected architecture is an entirely iPhone-local runtime on iPhone 17 / iOS 27.2: recognition, state/rules, Stockfish and speech. The Mac remains a build/evaluation host. The modules below are preparation for that integration; there is no completed, installed or hardware-validated iPhone app. The final full Node regression for the native backend/replay continuation passed **172/172**, with zero failures or skips, including the previously authorized loopback HTTP checks. The earlier 138-test count below belongs to the preceding simulation tree.

| Check | Observed result | Limit |
| --- | --- | --- |
| Installed SDK inventory | iPhoneOS and iPhoneSimulator 26.2 SDK paths exist; SDK queries succeed | Does not repair or explain generic Xcode destination selection |
| Direct DAT 1.0.1 device probe | Swift 6.2.4 typecheck exit 0, 8.20 s; unsigned library link exit 0, 1.03 s | Imports/typealiases only, no SDK calls or app build |
| Swift synthetic recognizer | 78 reused PNG frame records / 4,992 square decisions, zero Python/native disagreements including abstentions; geometry availability agrees | Mac port conformance for known artwork/markers, not fresh held-out or physical accuracy |
| Swift recognition of decoded video | 78 actual MP4-decoded frames / 4,992 decisions, zero Python/native disagreements; geometry agrees | Same synthetic sequence decoded by FFmpeg on Mac; no native iPhone video decoder or hardware result |
| Native capture contracts | 10/10 Mac mock lifecycle checks; direct iOS/DAT typecheck passed | Mock pixels/rules/engine/speech; no real camera or audio |
| Native local engine host | iOS ARM64 typecheck passed; separately authorized Mac WebKit fixture passed rules, actual Stockfish and cancellation in 1,482.83 ms | Mac fixture only; iPhone Worker/WASM, memory and app behavior unverified |
| Portable replay continuity bridge | 10/10 focused tests using real chess.js rules | Standalone and unbundled; explicit review fixtures and replay clock, no native continuity or output permit |
| Native recognition/rules/runtime adapters | 13/13 standalone Swift checks; complete iOS source typecheck passed | Mock transport/runtime plus frozen real DeviceBackend/Stockfish JSON acceptance, no additional WebKit/device/audio execution |
| Offline iPhone study app | 8/8 mocked lifecycle checks; full source compiled/linked and private resources assembled, no `LC_CODE_SIGNATURE` | Unsigned arm64 iOS 17.2 app; never installed/launched, no actual UI/pipeline or audio verification |

The DAT probe used the installed iPhoneOS 26.2 SDK and target `arm64-apple-ios17.2`. Read-only inspection found an arm64 iOS dynamic library with minimum OS 17.2, both DAT framework load commands and no `LC_CODE_SIGNATURE`. Its Mach-O build-version SDK field is 17.2, while the invoked SDK path/settings are 26.2; both facts are preserved without assigning a cause. The earlier generic `xcodebuild` simulator/device errors remain recorded failures, but the inference that a compiler SDK installation or upgrade was required is withdrawn. No app signing, installation, account, pairing or device action was performed.

The 78 vision records contain 37 distinct image hashes and 372 unknown-square decisions; agreement includes abstentions and is not 4,992 correctly identified pieces. Native vision also passed a direct iOS typecheck, but that mode excludes `SWIFT_PACKAGE`: `Bundle.module` and real package resource copying remain unverified. PNG port conformance does not establish native/Pillow JPEG or color-profile parity. The recognizer still emits review-only pieces with no inferred historical state. Native capture tests check bounded queues, frame/review identity, cancellation, legal-output validation through injected mocks and stale-speech rejection. DAT media timestamps are not treated as host capture times; unknown real capture age blocks all engine/speech permits.

The native runtime source serves bundled rules/Stockfish assets through an isolated WebKit host, without a Mac service. The user explicitly approved its bounded offline WebKit fixture. The first default-sandbox attempt exited 1 after macOS could not create WebKit/LaunchServices sandbox extensions. A separately approved single expanded-command run of the same executable and local v2 bundle exited 0: full starting-position validation, actual Stockfish `e4` with regenerated text, and cancellation passed in 1,482.83 ms; stderr was empty. This establishes custom-scheme modules and Worker/WASM for that Mac fixture. No browser profiles, camera, microphone, glasses or audible speech were used. iPhone behavior and app integration remain open.

The executable hash is `b4f09e58cc1d70cc58393cc70e041a98f8d96302cf377c96e2c7b1fb459680b8`; the tested host source hash is `52d82cc4b7d90318e011048324479d3d8ad968fcf8ede5c4130dbc20b9ff6713`. A subsequent entry cancellation check protects a newer request from an already-cancelled old task; that final source is compiled and contract-tested separately, without another WebKit execution. Exact commands, both outcomes, log hashes and scope are preserved in `outputs/native-readiness-2026-11-11/runtime/webkit-execution.json` in the continuation session.

The current private engine asset manifest is `471e56746249cb421a59c2466d2febf2ff1791af16b6391efb79aafb44fc47d5` (`work/iphone-runtime-assets-v2`). The earlier v1 manifest is preserved. The v2 backend echoes the original normalized FEN and checked move in rules replies for native validation. The full WASM is 99,169,054 bytes. This bundle does not yet include the standalone replay continuity bridge; no native continuous-game assembly is claimed. The runtime and integration Swift package manifests are source definitions only; package execution/resource assembly remains unverified.

`native/ChessCompanionIntegration` connects native recognition and capture contracts to local rules/engine transport. It validates exact full FEN, request/frame identity, safe JavaScript integer ranges and checked move fields. Invalid new requests revoke prior work; cancellation stays scoped to the owning task even across wrappers. The frozen real JS fixture used actual Stockfish with a 100 ms search request (depth 12, reported search time 105 ms); Swift accepted unchanged FEN, move, successor position, status and speech fields, with only request ID and test identity rebound. This verifies the cross-language JSON contract separately from WebKit. The synthetic adapter accepts only explicitly trusted replay frames and rejects DAT input. Evidence: continuation `outputs/native-readiness-2026-11-11/integration/summary.md`.

The offline app builds monolithically from exact shared-source snapshots. It assigns no live capture timestamp to the saved fixture and leaves live glasses mode unavailable. The first full compile hit a Swift 6.2.4 IR-generation crash; explicit SwiftUI callback closures fixed the second build without a toolchain change. Both logs and the successful resource/binary hashes are retained in continuation `outputs/native-readiness-2026-11-11/app/`. Binary SHA-256: `8e7a95adf261112068649dbb21850e756e4b15f98559fb52f77aae3632e09df4`. Package-based builds, signing/install, app launch, phone layout/performance and audible output remain unverified. The final full Node regression after app source changes passed 172/172; the mocked app checks are separately scoped.

Evidence: continuation [native-readiness outputs](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/), including [direct probe and binary inspection](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/direct-probe/summary.md), [vision conformance](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/vision/port-conformance.json), [vision build scope](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/vision/build-evidence.json) and [capture checks](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/capture/summary.json). Module contracts and remaining runtime gates are in `native/ChessCompanionVision/README.md`, `native/ChessCompanionCapture/README.md` and `native/ChessCompanionRuntime/README.md`.

## Completed simulation milestone — preceding verified tree

The simulation-first continuation is implemented: original vector-piece renderer, frozen legal fixtures, separated pixel index/truth sidecars, visible-marker/template pixel recognition, review-only UI/API, and actual PNG/decoded-MP4 evaluation through legal tracking, Stockfish and a **text-only** speech sink. The recognizer receives opaque image bytes only, without FEN, filenames encoding state, labels, seeds or scene metadata. The interactive app still requires real user review; the evaluator explicitly uses an automated initial-state fixture.

Final results for **each** input path (78 PNGs / 78 decoded MP4 frames):

| Check | Result |
| --- | --- |
| Development exact accepted boards | 54/54 |
| Held-out sequence/scene exact accepted boards | 14/14 |
| Challenge frames withholding guidance | 10/10 |
| Incorrect accepted squares / boards | 0 / 0 |
| Required stable legal full-state checkpoints | 34/34 |
| Stale-session probes blocking engine/text output | 15/15 |
| Actual bounded Stockfish → text speech | 1 legal recommendation |

Known template artwork and visible colored markers limit these results. Frames are correlated pairs; opening splits share an initial board and all positive frames share piece artwork. The challenge set covers hand-like occlusion, missing marker, unfamiliar slender pieces, white-patch glare approximation and severe blur. Motion is stepped, not continuous physical camera motion. Replay uses deterministic timestamps; per-frame wall medians were 267.55 ms (PNG) and 233.76 ms (decoded video), so this is not proof of live 10 fps processing. No physical-board, phone, glasses capture, actual browser interaction or heard-audio result is claimed.

Independent review fixed transparent inputs exposing hidden RGB pixels and an evaluation gap that allowed correct pieces to mask failed legal tracking. Nonopaque PNG/WebP inputs now reject, including palette transparency; opaque RGBA remains supported. Tracking coverage independently fails skipped-move sequences. Recognition thresholds/templates were frozen before first held-out inference and unchanged by these validation/scoring fixes. The initial report remains preserved separately.

At the end of that simulation milestone, combined `npm test`: **138/138 passed**, including 12 local HTTP tests and actual rendered pixels → review-only draft → explicit automated review fixture → real Stockfish → speech text. The local listener used the user's existing approval. Eight Python suites: **63/63 passed**, including 15 synthetic pixel, 11 manual calibration and existing recognition/metric tests. These runs predate the native continuation above. No original Apple Vision runtime retry was made: its recorded CVPixelBuffer blocker is unchanged. No additional CoreML model run was made in that final simulation regression.

The manual photo/corner flow also completed its actual development-image smoke: image-bound reviewed geometry, 64-square proposal, 35 explicit unknowns, every historical field unset, no engine/speech invocation, and request temporary files removed. These are workflow checks on an old development photo, not new physical accuracy.

Authorized dependency checks at that stage: DAT 1.0.1 resolved at revision `0bd369298eef6a980ad0bdb6c8a5502f2c02a08c`. Both generic signing-disabled compile checks exited 70 **before compilation**, reporting the missing iOS 26.2 platform. Import compatibility was untested then; the later installed-SDK inventory and successful direct probe above supersede that limitation for the small import/typealias surface. No installation/upgrade/signing/account/device action followed. The separate authorized GPU-visible CoreML comparison recovered the historical outputs but still failed 1/2,496 logits; the restricted-runtime 33/2,496 result remains separately preserved. Both authorized public media downloads returned HTTP 403; those acquisition routes are closed.

Evidence: continuation `outputs/simulation-2026-11-11/` contains `png-report.json`, `mp4-report.json`, the original report, frozen/final source hashes, corpus, video, quickstart and final verification logs. `outputs/completion-build-2026-11-11/` contains the manual-photo, CoreML, acquisition and SDK evidence. See `SIMULATION_PLAN.md` for commands and the optional later ordinary glasses capture of a displayed board. All prior dirty work and blackjack are preserved; no browser access or permanent permission settings were changed.

## Earlier continuation records

The following sections preserve earlier iterations; the dated results above supersede their current-status statements where new evidence exists. Older unknown-phone and missing-SDK statements are historical, not current blockers.

## Bounded numerical diagnosis — latest iteration

The original numerical failure was independently reproduced from preserved artifacts: one logit exceeds the unchanged tolerance. Model/reference hashes, normalized input bytes, tensor shapes/layout/class order, numerical comparison arithmetic and output indexing checked out. A separate versioned runner recorded one prediction followed by three on one loaded model: all four outputs per input were identical, but each full three-reference comparison failed **33/2,496 logits**, with all 192 labels matching. The unchanged pinned executable reproduced the current case-0 diagnostic output exactly. Numerical validation remains **failed**, with original and current results preserved separately.

Current runtime: macOS 15.7.4, CoreML 3405.2.1, requested CPU_AND_GPU, low-precision accumulation disabled; no default Metal device was visible. Exact backend/device assignment and the cause of changed historical outputs remain unproven. Shared compile/load was 1.468 seconds, and every measured prediction exceeded one second. No optimized runner, model replacement, tolerance/threshold change or live-deadline change was adopted. Details and exact decision: `NUMERICAL_DIAGNOSIS.md`.

One evidenced harness-provenance bug was fixed: `tests/recognition_whole.py` now removes inherited CPU-only configuration and checks every native output's explicit configuration before labeling/scoring it. This does not explain the saved outlier or repair numerical parity. **5 numerical/profile tests, 5 normalization tests and 42 review/lifecycle tests passed**; `git diff --check` passed. The initial default-temp-directory failure is retained; the successful invocation used the existing photo bridge's private-TMPDIR pattern within current writable paths, with no permission change. No original Vision retry, HTTP rerun, download, install, browser or device action occurred in this iteration. Outputs: `numerical-diagnosis-2026-11-11/` in the continuation session.

## Authorized HTTP follow-up — latest result

After the user explicitly authorized local loopback tests, `node --test tests/server.test.js` ran with per-command sandbox escalation: **7/7 passed**, exit code 0. This resolves the previous HTTP EPERM blocker for this authorized run. Coverage includes request/confirmation contracts, real local Stockfish over HTTP, cancellation/client disconnect, stale engine/recognizer rejection, image request limits and review-only recognition output.

Together with the earlier **93/93 non-HTTP Node tests**, all **100 Node tests passed across the two runs**; the earlier **35/35 Python tests** also passed. No implementation changed between those final runs. This is not a fresh combined full-suite invocation. No permanent permission configuration, browser or device access was used. The recognition, numerical, latency, new-footage and physical-device limitations below remain unchanged.

Exact command/output and authorization scope: session outputs `http-verification-2026-11-11/`. Earlier statements that HTTP tests were excluded or permissions were not expanded describe those earlier iterations; this follow-up used only the newly authorized test scope.

## Recorded input and measured processor latency — latest iteration

Added a bounded `RecordedFrameQueue`: one active processor plus one latest pending frame, explicit offline source/session/sequence identity, monotonic timestamps, actual frame-byte hashes, an 8 MiB frame bound, freshness watchdog, cancellation and review-only results. Reconnect, delayed completion, ignored aborts, serialization callbacks and changing input properties cannot restore old guidance or bypass frame ordering/bounds. The queue is not wired to an engine, speech, browser or glasses SDK.

Final permitted tests: **93/93 Node**, including **19 queue regressions**, and **35/35 Python**. Real local Stockfish is included in the Node suite; most capture/output lifecycle cases use injected adapters. The seven HTTP cases remained excluded because their loopback EPERM restriction was already recorded and retrying was declined. No original Vision runtime retry occurred. `git diff --check` passed.

Actual offline photo-processor checks used only the old Staxringold development image:

- An explicitly offline 15-second queue window produced a review-only proposal in **11,582.52 ms**, preserving `numericalValidationPassed:false` and exact model/runner/frame hashes. No engine or audio was attached.
- The unchanged default **1,000 ms** deadline aborted the real processor; it settled in **1,097.02 ms**, published no proposal and left no new request temp directories. This measures watchdog/process cleanup, not a hard real-time guarantee.
- A second standalone process completed in **11,423.94 ms**. Compile/load took 1,653.10/1,391.13 ms; individual predictions in the shared loaded model took **2,797.89–3,549.30 ms**. The existing runner makes three predictions per image. These are cached-environment diagnostics, not a clean cold-start or device benchmark. Startup is not dominant; a persistent worker alone cannot meet one second. No deadline, pinned runner, threshold or numerical gate was weakened. See `LIVE_PIPELINE.md` for stage timings and the next separately versioned single-pass diagnostic.

Connected page retrieval found two public, distinct-author video candidates with source/license evidence. One ordinary native media download per candidate failed with `URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>`. No retries, permission changes or browser fallback followed. No new frames, labels or recognition scores exist; source suitability and training overlap remain unknown. `PUBLIC_VIDEO_SOURCES.md` records the candidates and the accessible-media dependency. The automatic geometry arm was **not run**, not scored as abstention.

Final branch/HEAD remain `main` / `412397d513c99cb2f1485b676ff033563d2947f2`. Blackjack remains clean at `c60a2d16087e5def1681538b13ec0c2697d24046`. Prior dirty work, historical media/model artifacts and earlier evidence were preserved. No browser, permissions, installs, SDK/device setup, commit, push or publication occurred. Session outputs: `/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/recorded-input-2026-11-11/`.

## Geometry-comparison iteration — November 11, 2026

The proposed **new held-out A/B experiment did not run**: no ready fresh independently annotated local set has all four visible corners, and the existing Apple Vision execution failure remains unresolved. No permission expansion, browser, alternative detector/runtime bypass, downloads, installations or SDK/device setup occurred. The inspected unused Pexels 6184294 samples are cropped/blurred/occluded and unsuitable for clean geometry isolation; upstream training overlap is also unknown. Paired phone details remain unknown and are not a prerequisite for this offline work.

Completed instead:

- Added `scripts/recognition/replay_geometry_comparison.py` and `paired_metrics.py`: strict recorded-artifact comparison using the same cstr classifier contract and preexisting fixed canonical orientation. No new detector/classifier inference runs inside the evaluator. It binds source/model/code/manifest hashes, joins geometry artifacts to their historical run, rejects malformed geometry and mismatched source/model/threshold data, separates runtime errors from genuine detector abstention, and always labels the result development replay.
- Replayed the existing five diagnostic video frames. Automatic geometry abstained 5/5 times, so raw classifier accuracy is **null**, not 0%. The annotated-corner control has 7/74 raw known occupied types correct; **0/74 accepted-correct yield**, and **15/15 accepted known occupied-type predictions wrong** (all false empty). Unknown/occluded cells remain unscored; exact-board accuracy is null for both arms. Full denominators and class/color/score-bin/temporal analysis are in `PAIRED_EVALUATION.md`. No confidence threshold or recognition behavior was tuned. Evaluator/error reporting improved; recognition accuracy did not.
- Verified the existing CPU ONNX classifier still runs on one reused development frame, reproducing all 64 saved labels and confidence values exactly. Approximate load 446 ms, crop/inference 510 ms, one Mac diagnostic. This checks the existing classifier path only; it is neither a Vision replacement nor a fresh held-out result.
- Tested an actual saved erroneous proposal against the current draft/live boundaries: all historical fields stay unknown, incomplete FEN validation fails, direct proposal ingestion is rejected, and **zero engine calls / zero spoken messages** occur. `LiveSession` still requires a separate caller human-review assertion and valid fresh stable legal observations; that boolean is caller responsibility, not proof of actual human review.

Fresh permitted regressions: **74/74 Node tests**, **35/35 Python tests**. The Python total includes 18 new metric/artifact-boundary regressions plus the existing 17. Actual app-handler tests cover complete draft-history/review gating and stale imports; existing observation/live-session tests cover unknown squares, illegal/skipped transitions, stability/timeouts and stale speech. No redundant live-state subsystem was added. `git diff --check` passes.

The seven HTTP tests were excluded due to the previously recorded loopback EPERM and the instruction not to retry. Native Vision calibration, a new held-out geometry run, fresh full two-arm inference, numerical CoreML revalidation, browser recognition, physical capture and actual audio remain not run. Previously recorded exact environment errors remain in the earlier record below.

Reproducible protocol/results: `docs/PAIRED_EVALUATION.md`. Session outputs: `/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/geometry-comparison-2026-11-11/paired-replay-verified.json`, `classifier-runtime-check.json`, `review-boundary.json`, and `checks/`. Original evidence artifacts were not overwritten. Blackjack remains clean; no commit/push/publication.

The small next data requirement is a new source-disjoint recording with all four playing-surface corners, visible canonical coordinate evidence, several varied positions, frozen timestamps/corners, and independently reviewed per-square piece/color/occupancy labels with unknown reasons. Keep hand/motion/partial-board segments as separate abstention challenges; keep another source untouched for any tuning. Record training-exclusion evidence where available, otherwise state unknown overlap. Both arms must then run the same unchanged classifier/preprocessing in an authorized environment with the original detector functioning. Legal histories are not invented for geometry scoring; real continuous guidance needs a separate reviewed initial state and device tests.


This continuation reconciled the prior-worker handoff and preserved the existing dirty tree before completing focused fixes. Branch remains `main` at `412397d513c99cb2f1485b676ff033563d2947f2`; no commit, reset, cleanup, push or deployment. Blackjack remained clean at `c60a2d16087e5def1681538b13ec0c2697d24046`. No browser, camera, microphone, Bluetooth or permission changes were used.

## Current fixes and fresh permitted checks

- Photo proposals keep turn, castling, en passant and both move counters unknown. The editor requires explicit values, including an explicit castling-none choice. Invalid drafts clear the FEN preview; direct FEN loading cannot bypass draft review. Delayed JSON imports cannot overwrite resets, confirmations or newer imports. These are actual app-handler tests in a minimal DOM harness, not a browser test.
- LiveSession retains speech cancellation identity after an adapter acknowledges queued audio. Uncertainty, changed board, timeout, reconnect and stop abort queued/current output. Failed speech, including non-Error rejection, cancels output and permits retry. Adapter compliance and real audible output remain unverified.
- Numerical model diagnostics preserve the JSON/stdout report and exit 1 when numerical validation fails. The saved failed report exercised this path; the comparison itself still fails one logit and inference was not rerun.

Final permitted Node suite: **74/74 passed**, excluding `tests/server.test.js` because retrying its seven blocked loopback cases was explicitly declined. This suite includes real local Stockfish startup, legal move/mate, timeout/cancellation, legal tracking, review/import guards and speech lifecycle mocks. Exact command selection and output are in the continuation outputs. The prior worker's historical 76/76 pass predates these fixes and does not certify this tree.

Python offline regressions: **17/17 passed** (`recognition_numerical_gate.py`: 3, `recognition_video.py`: 5, `recognition_video_controls.py`: 4, `recognition_photo.py`: 5). These verify report exit status, partial-label scoring, crops/transforms and normalization, not real-board accuracy.

`node scripts/replay-live-session.js` passed with synthetic reviewed square labels, actual Stockfish, and text-only speech: “pawn from e2 to e4.” at reported depth 11. No camera or audio output was used. `git diff --check` passed.

## Blocked or unverified in this environment

Initial `npm test` ran 76 tests: 69 passed; seven HTTP cases failed to bind loopback with `Error: listen EPERM: operation not permitted 127.0.0.1` (`code: EPERM`, `errno: -1`, `syscall: listen`). They were not retried after the instruction to leave permissions unchanged. This is a runtime restriction, not evidence of seven application assertion failures; final HTTP behavior remains unverified here.

Swift compilation succeeded with an explicit `/tmp` module cache after the default cache location was denied. Apple Vision execution then exited 1 with `sysctlbyname for kern.hv_vmm_present failed with status -1` and `NSOSStatusErrorDomain Code=-6662`, “Failed to create CVPixelBuffer Width = 256, Height = 256, Format = 'BGRA'”. This occurred in sandboxed execution; its root cause is not proven. No fresh macOS calibration or video inference succeeded, and no permission expansion or browser fallback was attempted.

Current browser recognition journey, audible speech, paired phone/OS, Meta registration/capture, Gen 1 audio routing and camera/audio coexistence remain unverified. Current iOS sample requirements exceed the previously recorded local toolchain. Official iOS issue #358 also reports camera/TTS contention on Gen 2; applicability to this Gen 1 pair is unknown. See `HARDWARE_COMPATIBILITY.md`.

## Recognition evidence remains a failed gate

Saved genuine-video results: automatic geometry **0/5 detections**; raw whole-photo classifier **0/74 known occupied types correct**, with **120/236 accepted known labels wrong**; annotated-corner ONNX control **7/74 known occupied types correct**. Unknown/occluded predictions were often accepted. The tiny 2/3 exact starting-photo result does not establish general accuracy.

This continuation reproduced all saved metrics for the ten raw/rotation predictions using the current scorer and frozen labels, without rerunning inference. The current evaluator hash differs from the saved report for an unknown reason; manifest and preprocessing hashes match. Historical evidence remains unchanged. No exact-position or complete-FEN score is available for the partial-label video; four-second sampling cannot validate the default one-second tracker freshness window.

Snapshot, logs and exact error text are preserved under `/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/`. `docs/VIDEO_EVALUATION.md` specifies the next held-out comparison of automatic and independently annotated geometry. Automatic vision-to-speech remains disabled.

---

# Historical baseline verification — November 10, 2026

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
