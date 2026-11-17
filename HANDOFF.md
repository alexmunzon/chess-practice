# Chess glasses handoff — November 12, 2026

## Direction and checkpoint

Alex chose **recognition, chess rules, Stockfish and speech entirely on the iPhone**, without a Mac runtime service. Target: reported iPhone 17 / iOS 27.2 and Ray-Ban Meta Wayfarer Gen 1. Alex has no physical board, so the current test bed uses generated screen-board images/video. The live glasses product is **not complete or hardware-validated**.

The latest Mac run recorded intermediate Stockfish output and delivery of the 100 ms page probe. It captured neither the 1,000 ms probe nor the 2,500 ms search timer callback. Swift timed out about 15 seconds after dispatch, then the trace recorded Swift's cancellation dispatch and the same analysis's JavaScript abort handler. The snapshot closed before an analysis reply arrived, so the reply error code remains unknown. Synthetic recognition and FEN review passed again. The composed flow remains incomplete. [Timer trace checkpoint](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-timer-trace-2026-11-12/STATUS.md), [workflow](/Users/alexmunzon/Documents/Codex/2026-10-30/task-3/chess-practice/docs/WORKFLOW.md).

Project: `/Users/alexmunzon/Documents/Codex/2026-10-30/task-3/chess-practice`.
Continuation workspace: `/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at`.
Evidence root: [native-readiness-2026-11-11](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/STATUS.md).

## Implemented and measured

| Area | Result and evidence |
| --- | --- |
| Full Node regression | **172/172 passed**, no failures/skips; [log](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/verification/node-tests.txt). Includes real Stockfish WASM, local HTTP tests, strict native JSON backend and replay tracking. |
| Simulation corpus | 78 PNG records and aligned 78-frame MP4; each original evaluation accepted 68/68 positives exactly, blocked 10/10 challenges and matched 34/34 legal-state checkpoints. [Quickstart and limits](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/simulation-2026-11-11/QUICKSTART.md). Speech evidence was text-only. |
| Swift synthetic recognition | Zero decision disagreement across 4,992 cells of the source PNGs and separately across 4,992 cells of actual MP4-decoded frames. These include abstentions and repeated/correlated images; the PNG records contain 37 distinct images. [PNG report](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/vision/port-conformance.json), [video report](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/vision/video-native-port-conformance.json). Known synthetic artwork/markers only; Mac timings are not iPhone performance. |
| Native capture lifecycle | **10/10 mock checks** and iOS/DAT source typecheck. Unknown DAT capture age blocks engine/speech permits. [Evidence](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/capture/summary.md). No SDK capture or audio was run. |
| Native adapters | **13/13 checks**, real DeviceBackend/Stockfish JSON accepted by Swift, and final combined iOS source typecheck passed. Exact FEN/identity/move validation and task-scoped cancellation. [Evidence and commands](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/integration/summary.md). |
| Mac WebKit engine | User-approved isolated, nonpersistent, local-only fixture **passed** rules, actual Stockfish `e4` and cancellation in **1,482.83 ms**. First restricted-sandbox attempt failed to start WebKit services; the separately approved expanded run succeeded. [Both outcomes and exact executable/source hashes](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/runtime/webkit-execution.json). No audible speech, existing browser profile or device used. |
| Replay continuity bridge | **10/10 focused tests** with real chess rules, explicit complete initial review and replay clock. [Contract](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/tracking/README.md). Standalone/unbundled; it cannot authorize output and is not yet native continuous-game tracking. |
| Offline iPhone app assembly | **8/8 mocked lifecycle checks**; full SwiftUI source compiled/linked and resources assembled for arm64 iOS 17.2 using installed iOS 26.2 SDK, with no code signature. [Build evidence](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/app/summary.md). Never launched, installed or used for audio. Initial compiler IRGen crash and successful explicit-closure fix are both preserved. |

The preceding simulation tree also passed 63 Python checks; native vision subsequently passed six boundary checks and fixed-input pixel comparisons. These are separate suites/scopes, not additional physical-board accuracy.

## SDK correction and remaining blockers

DAT is pinned to **1.0.1**, revision `0bd369298eef6a980ad0bdb6c8a5502f2c02a08c`. Both iPhoneOS and iPhoneSimulator **26.2 compiler SDKs are installed**. Installed Swift **6.2.4** successfully imported and unsigned-linked the minimal DAT device-target library. Earlier generic `xcodebuild` exit-70 destination errors did not prove the SDK was absent; do not recommend an install/upgrade from those errors alone. [Inventory](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/inventory.md), [direct probe](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/direct-probe/summary.md).

- Physical-board/piece recognition remains unreliable. Synthetic conformance does not qualify the physical models. The authorized CoreML comparison still failed 1/2,496 logits under the unchanged tolerance. The two approved public video downloads returned HTTP 403; those routes remain closed.
- DAT media PTS and host receipt time do not establish capture age. A measured clock mapping/latency bound is still required; never relabel receipt time as capture time or use trusted replay as a live workaround.
- Native capture currently binds review to one frame; the standalone replay tracker is not connected to native persistent game state. Human review needs time, followed by fresh agreeing frames; missing historical state must never be inferred.
- Camera streaming versus Bluetooth/TTS audibility is unresolved. Stop-stream acknowledgement is an experiment prerequisite, not a verified fix. No actual audio or glasses route has been tested.
- iPhone runtime/performance, full application resource/runtime behavior, signing, installation, Meta registration/permissions, firmware/companion versions, pairing, camera capture and actual speech require separate verification. Current direct source checks do not prove those outcomes. SwiftPM manifest execution previously failed its nested sandbox; do not bypass it silently.
- The successful WebKit fixture executed host source `52d82cc4…`; the final host adds a pre-cancelled-task guard (`47564b0a…`) checked by compilation/contracts, without another WebKit run. The private runtime bundle is v2, manifest `471e56746249cb421a59c2466d2febf2ff1791af16b6391efb79aafb44fc47d5`; full WASM is 99,169,054 bytes. Keep generated binaries private/outside the checkout and preserve notices; distribution/source-delivery obligations are not declared complete.

## Reproduction and permission boundaries

From the project directory:

```sh
npm test
node --test tests/device-game-session.test.js tests/device-backend.test.js tests/worker-engine.test.js tests/device-runtime-assets.test.js
```

Exact completed Swift commands and artifact paths are recorded in [capture commands](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/capture/commands.sh) and [integration commands](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/integration/commands.sh). [Video decode provenance](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/vision/video-decode-provenance.json) retains exact FFmpeg/comparator invocations. Choose new empty external output folders; retain the saved reports rather than overwriting them.

The most recent corrected private unsigned app is `/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/work/iphone-offline-app-confidence-fix/ChessCompanion.app`; executable SHA-256 `a7d8c8bc60c1a5f31d573a7b8b8b09163896b3c3ae380f5628742a92eeb66080`. The earlier v2 artifact and its evidence remain preserved. It is not installable as delivered. Source, scope and exact unsigned assembly entry point: [native/ChessCompanionApp/README.md](/Users/alexmunzon/Documents/Codex/2026-10-30/task-3/chess-practice/native/ChessCompanionApp/README.md). To reproduce with a new empty output directory:

```sh
python3 -B native/ChessCompanionApp/prepare_app.py \
  --out /tmp/chess-offline-app-new-build \
  --runtime-assets /Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/work/iphone-runtime-assets-v2 \
  --fixture /Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/simulation-2026-11-11/corpus/pixels/000000.png
```

Existing authorization covered local HTTP tests, the completed three-input CoreML comparison, the two completed public download attempts, isolated DAT acquisition/unsigned compile checks, and the completed specific WebKit fixture plus one expanded-command rerun. It is not blanket browser/device permission. **Do not access a browser, broaden permissions, install/sign/deploy, operate a phone/glasses/camera/microphone/Bluetooth, or play audio without the required authorization.** No permanent permission/settings changes, account actions, commit/push or deployment were performed.

## Git and review handoff

Chess remains on `main`, HEAD `412397d513c99cb2f1485b676ff033563d2947f2`; existing dirty/untracked work was preserved. Blackjack remains at `c60a2d16087e5def1681538b13ec0c2697d24046` and was clean on inspection. No commit/reset/clean/stash/push was performed.

This continuation adds native Vision/Capture/Runtime/Integration/App sources, portable Worker/backend/replay bridges and tests, local asset assembly and evidence docs. Earlier uncommitted simulation/manual-photo/UI/server/calibration work remains present. The [final checkpoint inventory](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/checkpoint/git-status.txt) records every modified/untracked path; do not treat all dirty files as this packet's changes. [Source hashes and Git identities](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/checkpoint/source-state.json) include the local `AGENTS.md` workflow update even if Git excludes that instruction file.

Independent reviews corrected deadline publication, abort reentry, strict native JSON validation, operation-scoped cancellation and packaging provenance. App review fixed foreign-reply cleanup, exact installed/locked version and MIME checks, and compile-from-snapshot provenance. The final mocked app test explicitly waits for late recognition completion. Completed scopes reported no remaining concrete issue; this is source review, not UI/hardware validation. Final full `npm test` passed 172/172 after app source changes; `git diff --check` passed. [Checkpoint review record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/checkpoint/review.md).

## Composed-study packet — checkpointed after diagnostic failure

**Completed work:** the prior integer-confidence fix and rebuilt artifacts were inspected, not rebuilt again. A fresh reviewer and preflight verified 10 source files, 15 assets and executable hashes. One specifically approved corrected Mac run failed after 21,932.40 ms with a generic native deadline error; its cycle/operation remained ambiguous. Evaluation-only diagnostics were added in `VerifyComposedStudy.swift`, `ComposedStudyDiagnostics.swift` and `ComposedStudyDiagnosticsChecks.swift`. All nine production sources, deadlines, engine assets and original acceptance predicates were preserved. No physical-model, SDK or download experiment was repeated.

**Measured diagnostic run:** one new specific approval was obtained. Automatic permission review initially timed out before dispatch; its permitted retry launched exactly one process. The result was `firstAnalysis`, analyze ordinal 1, 15,010.27 ms operation time and 21,536.72 ms total, exit 1 and empty stderr. Eleven assertions passed: pinned inputs/runtime manifest, local asset readiness, the expected 16 unknowns and blocking, exact 64-cell agreement, no inferred review/history, incomplete/mismatched-review blocking and full reviewed FEN validation. Review was a scripted fixture, not live human review. There were **zero legal-text and text-sink calls**. No Stockfish result, explicit output, edit/reset acceptance or delayed-background acceptance was reached. Worker creation/UCI/search/JS delivery remains unobserved. [Execution and bounded trace](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/diagnostics/execution.json).

**Other verification:** pure Foundation diagnostics **17/17**, full `npm test` **172/172**, and a Node comparator passed two unchanged 1,000 ms searches plus separate legal-text checks in 1,467.15 / 1,361.74 ms. Node success is a different-runtime comparator, not a WebKit cause or pass. Independent review found no remaining concrete issue in the observational change and verified all 11 compiled snapshots, the executable and the result interpretation. [Review](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/review.md), [Node comparator](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/node-budget-probe.json), [diagnostic tests](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/diagnostics/verification.json).

**Exact prepared/executed artifact:** [diagnostic preparation](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/diagnostics/preparation.json) contains the compiler command, snapshot paths, run command and hashes. Mac executable SHA-256 `9b36cb2e89ccc85a6bd9af50ae42135f17cc529a7b61a93368cb64705908c984`; it reads the corrected unsigned iOS bundle as data and never invokes its executable. Both one-run approvals in this continuation are consumed. Do not rerun it automatically.

**Changed in this resumed packet:** only the three evaluation files listed above plus handoff/status documentation. Existing app/runtime/recognizer/engine production files and blackjack remain unchanged. Full preexisting dirty work remains uncommitted. [Final inventory](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/git-status.txt) and [source hashes](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/source-state.json) distinguish this checkpoint from earlier ones.

## Dispatch and Worker trace packet — checkpointed

**Observed.** The instrumented Mac process exited 1 after 24,662.15 ms. The first analyze operation reported a 15,008.74 ms deadline. The position validation request had a JS reply and native receipt. For the separate analyze request the trace recorded native dispatch, JS submit, Worker construction, `uciok`, `readyok`, the Go post attempt and native timer expiration. The trace recorded no `bestmove`, engine completion or failure, JS analysis reply, legal-text call or text-sink call before its snapshot. [Execution record and exact command](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-trace-2026-11-12/execution.json).

**Verification.** `ComposedWorkerTrace.swift` and `prepare_worker_trace.py` generate the Mac-only trace in private snapshots and a hash-checked resource mirror. The production sources and the two fixtures remain byte-for-byte unchanged. Independent review rehashed all 12 Swift snapshots and 15 assets and checked the interpretation of the run. The Node simulation verified milestone order and per-request correlation. The full Node suite passed 172/172. [Preparation](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-trace-2026-11-12/reviewed/preparation.json), [focused check](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-trace-2026-11-12/reviewed/focused-node.json), [review](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-trace-2026-11-12/STATUS.md).

## Go post, Worker callback and timer trace — checkpointed

**Observed.** The one requested Mac run used the same 1,000 ms search, 1,500 ms grace and 15,000 ms native deadline. It recorded `goPostReturned` and `firstWorkerMessageAfterGo` on the same analysis transport. The Worker message payload was outside the trace. There was no observed `workerErrorAfterGo`, `workerMessageErrorAfterGo`, `searchTimerFired` or `bestmove` before the snapshot. Swift's timer fired, then the trace recorded entry into JavaScript finish and a failed reply. The reply's error code was outside the trace. This ordering is consistent with native cancellation, and does not explain the missing search timer marker. The process exited 1 after 21,626.99 ms with empty stderr and zero legal-text or text-sink calls. [Execution record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-search-trace-2026-11-12/execution.json).

**Verification.** Five simulated Worker cases and all 172 Node tests passed. Independent review verified the marker boundaries, unchanged deadlines and artifact hashes, and checked the observed run. The production runtime and iOS app retain their prior evidence. [Preparation](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-search-trace-2026-11-12/preparation.json), [focused checks](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-search-trace-2026-11-12/focused-node.json), [raw Mac report](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-search-trace-2026-11-12/mac-run.stdout.json).

## Page timers, Worker categories and cancellation trace — checkpointed

**Observed.** The one requested Mac run used the same 1,000 ms search, 1,500 ms grace and 15,000 ms native deadline. After Go, the first eight sampled Worker callbacks classified as one `infoString` and seven `infoDepth`, followed by the sample limit marker. The 100 ms page probe fired 100 ms after scheduling by the page clock. The trace contained no 1,000 ms probe, search timer, Worker error or best move. The native timer fired 15,011.95 ms after dispatch. Swift attempted cancellation, and the same analysis's abort handler marker arrived 12.86 ms after that dispatch marker by the native clock. The trace ended before engine finish or a reply arrived. It captured no error code. The process exited 1 in 22.72 seconds with zero legal-text or text-sink calls. [Execution](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-timer-trace-2026-11-12/execution.json), [raw trace](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-timer-trace-2026-11-12/mac-run.stdout.json).

**Verification.** Seven simulated Worker cases and all 172 Node tests passed. Independent review checked the evaluation trace, source and asset hashes, and observed result. The trace classifies the leading token of at most eight Worker messages per analysis and records only allowlisted reply error codes. The native and JavaScript clocks remain separate. [Preparation](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-timer-trace-2026-11-12/preparation.json), [focused tests](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-timer-trace-2026-11-12/focused-node.json).

## Detached WebKit scheduling comparison — checkpointed

One approved Mac probe used two fresh, undisplayed, nonpersistent views with the pinned v2 assets, seven-second idle interval, same FEN and 1,000 ms Stockfish search. The default case failed at analysis with a native deadline error after **15,984.23 ms**. The comparison case with `.inactiveSchedulingPolicy = .none` exited analysis after **1,659.30 ms** with `Invalid local engine reply.` The probe incorrectly required `bestMove.uci` and `analysis.elapsedMs`, fields omitted by the production backend. A valid response would fail that guard. The host can also emit the same error, so the report cannot establish valid output. Fixed case order is another limitation. The probe exited 1 with empty stderr and its approval is consumed. The raw report is retained in the November 12 continuation's `work/webkit-scheduling-probe/mac-run.stdout.json`.

## Composed WebKit scheduling fix — verified on Mac

The detached WKWebView uses the public inactive scheduling policy `.none`. A separately approved Mac run with the original composed harness and matching input hashes passed in **17.89 s**. Only the production host source differed from the previous composed compile. Three 1,000 ms Stockfish searches and three separate legal-text checks completed. The first result was `e2e4`, with two explicit calls to the text-only sink. Occlusion, incomplete/mismatched review, edit/reset and late completion after backgrounding passed. The full run report is under the November 12 continuation's `outputs/Composed-Mac-Result.json`. This approval is consumed.

## Multi-position Simulator preparation — historical compile checkpoint

The offline study now offers Starting position, After 1. e4, En passant, Promotion and Obstructed board. Exact PNGs are pinned in the existing build script. An explicit button can load a sample draft FEN for a complete position. The five review fields, local rules validation and identity-bound analysis remain required. Switching positions revokes output and clears image, review and FEN. Simulator output is text only.

The arm64 Simulator and single-fixture arm64 device bundles both compiled and linked without signing. The full Node suite passed 172/172, and the mock lifecycle suite passed 10/10 including a held analysis reply returned after switching. The Mac native recognizer matched 64/64 squares for each of the four playable PNGs and left 16 unknown on the obstructed image. The Mac manifest probe rejected partial, extra and tampered inputs. Four real Node Stockfish searches returned separately rules-checked recommendations. These are separate from Simulator execution. Artifacts and exact source hashes are in the November 12 continuation's `work/simulator-offline-study/` and `work/iphone-legacy-study/`. Exact compiled and checked source hashes are also in `outputs/Simulator-Build-Evidence.json`.

**Acceptance.** Local Simulator ad hoc signing and the install/launch/UI check require the pending scoped authorization. Use the existing iPhone 17 / iOS 26.2 Simulator and the separate chess Simulator bundle ID. Verify distinct positions produce fresh legal text, and switching and obstructed input clear or block it. Physical iPhone, audible speech and glasses operations remain outside this milestone.


## Remaining Simulator race verification — recorded November 13

All four playable fixtures have now completed the actual Simulator recognition → explicit FEN review → validation → analysis flow. Promotion returned legal `e1e2` (“king from e1 to e2”), separately rules/text checked; earlier moves were `e2e4`, `c7c5`, `e1d2`. The obstructed board exposed 16 unknown squares and blocked advice. Actual UI checks also passed for invalid rules-state FEN with matching pieces (side-to-move `x`), background/foreground review and recommendation invalidation, and reset after backgrounding. A rapid Analyze → Home sequence completed its UI actions within 290 ms; returning showed no stale recommendation and unchecked review. This does not prove exact engine receipt time or delivery of a late callback.

No app source changed in this follow-up; current source and signed artifact hashes match the prior build. A freshly compiled standalone mock lifecycle suite passed 10/10, including held analysis reply after a position switch. Prior 172/172 Node regression remains applicable to the hash-matched source and was not needlessly repeated.

Remaining strict acceptance limit: exact in-flight position-switch timing could not be reliably observed through CUA navigation within the one-second search. Keep the held-reply mock evidence distinct from actual Simulator execution; do not claim the full strict checklist is complete. No new runtime failure or code defect was found. Local Simulator approval is already granted and remains valid for the same scope. No physical phone, glasses, capture-age or audible-output validation, commit, push or distribution occurred.

Current evidence and quickstart: `/Users/alexmunzon/Documents/Codex/2026-11-12/task/outputs/chess-simulator-followup-2026-11-13/` (`results.json`, `identity.json`, `promotion-rules-check.json`, `mock-lifecycle.json`, `Quickstart-and-results.md`). Historical evidence remains untouched in the adjacent `chess-simulator-runtime/` folder.

**Goal:** observe an actual fixture switch before the same search completes, if UI timing can be reliably reached; otherwise retain this precise limitation. **Relevant files:** OfflineStudy.swift and OfflineStudyChecks.swift (unchanged); current evidence above. **Constraints:** existing local Simulator scope only; preserve review/invalidation gates and all existing work. **Acceptance:** actual event ordering must be observed before claiming this race passed in the Simulator. **Stop:** unresolved UI timing capability, completed strict acceptance, or user stop. No controller or automatic retry loop. Normal offline study is usable with the documented verification limit.


## Active task packet — private phone build prepared; physical approval pending

Alex reconfirmed the reported phone as **iPhone 17 / iOS 27.2** on November 13. This remains user-reported, not physically queried. The unchanged Simulator-tested source compiled and linked successfully as a private unsigned arm64 iOS device app with all five study fixtures, using the installed iPhoneOS 26.2 SDK path supplied to Swift and deployment target 17.2. The Mach-O itself encodes minimum OS 17.2 and SDK 17.2; both observed facts are retained without assigning a cause. All 46 artifact checks passed. The unsigned executable SHA-256 is `43a02cdeed2143bec10fa06afd8d456efb76583ec6c806616a7a2f607edbbdb6`; bundle ID `local.chesscompanion.offlinestudy`. Actual iOS 27.2 compatibility and phone performance remain unverified.

Evidence and exact prepared artifact: `/Users/alexmunzon/Documents/Codex/2026-11-12/task/outputs/iphone-offline-preparation-2026-11-13/` (`Phone-build.md`, `build-report.json`, `verification.json`). Prepared unsigned app: `/private/var/folders/40/pkx1ymn10_s42501bl5799wh0000gn/T/chess-iphone-study-ruo4lyj9/build/ChessCompanion.app`. No app source changed. No signing identity, profile, account or physical-device inventory was queried; no signing, installation, launch, audio or glasses operation occurred.

Physical-phone approval is still required to inspect the actual connected target/existing signing setup, sign using an existing configured identity/profile if available, install, launch and exercise this private app with text-only output. Stop for new accounts, registration, credential entry, spending or permanent settings changes. Simulator approval does not cover physical-device actions. Do not invent a device ID, team, identity, profile or successful compatibility result. The separate actual-UI in-flight fixture-switch timing limit remains documented; its mock passed 10/10.

**Goal:** after explicit approval, verify the target and existing provisioning, then sign/install/test the prepared offline app. **Acceptance:** actual phone/OS evidence, verified signature, installation/launch outcomes and offline study/safety checks. **Constraints:** no new account, spending, registration, credential entry, permanent settings, capture or audio operations under this proposed scope. **Stop:** missing physical approval, unavailable provisioning, an independently required user action, or verified phone milestone. Preserve all old evidence and dirty work.


## Active task packet — phone verified, signing identity is the one blocker (November 15, 2026)

Ownership moved to Claude (Fable orchestrating subagents). The project now lives at `/Users/alexmunzon/chess-practice`, copied from the Codex checkout, which is kept untouched as a backup. Earlier sections keep their original paths as historical record. The "physical approval pending" wording in the packet above is stale: Alex approved inspecting the phone and existing signing setup, then signing, installing and opening the private app for text-only offline testing.

**Measured on November 15.** `npm test` passed 172/172 in the new folder. `xcrun devicectl` reported the phone as connected, paired, Developer Mode enabled, iPhone 17 (iPhone18,3), iOS 27.2 build 24B119, CoreDevice identifier `0CE608CB-28E6-5A15-9B27-AAE6A9FDFC4A`. This replaces the user-reported model/OS with a device query. `security find-identity -v -p codesigning` reported 0 valid identities; there are no provisioning profiles and no Apple ID in Xcode. The prepared unsigned app still exists and its executable still hashes to `43a02cde…dbbdb6`. Xcode is 26.3; whether its device support runs an app on iOS 27.2 is unverified until a launch is attempted.

**Goal:** sign, install and launch the prepared offline app on the phone, then run the text-only study checklist in `Phone-build.md`. **Relevant files:** `native/ChessCompanionApp/signing/` (new kit: provisioning shell project and `sign_and_install.sh`). **Human prerequisite:** Alex adds his Apple ID in Xcode > Settings > Accounts; agents never enter credentials. Automatic signing then registers the phone and bundle ID under his Personal Team, which needs his explicit yes. **Acceptance:** verified signature, install and launch outcomes on the real phone, four playable fixtures plus obstruction and invalidation checks, measured responsiveness. **Stop:** missing identity, a required user action, or the verified phone milestone. Camera, microphone, Bluetooth, glasses and audible speech stay out of scope.

**Kept limit:** exact in-flight fixture switch during the one-second search is still unobserved in a real UI; the held-reply mock (10/10) remains separate evidence.


## Active task packet — certificate created; iOS platform installation in progress (November 15, 2026)

Alex signed into Xcode himself and explicitly approved using the Personal Team labelled Peter Munzon (FBYX5879MJ) to register the connected iPhone 17 and local.chesscompanion.offlinestudy and create the development certificate/profile. This supersedes the missing-identity and missing-registration-approval status above. Agents did not enter credentials or export private keys.

Executed the kit at native/ChessCompanionApp/signing/. Initial preflight confirmed connected phone and exact unsigned app hash but failed for no identity. Provision attempted the specific device, which Xcode rejected because its iOS26.2 platform package is marked not installed; the generic fallback created an Apple Development certificate but failed to create a phone profile (no eligible devices). Certificate creation was confirmed in both security find-identity and Xcode Manage Certificates. A second preflight passed. No sign/install/launch stage has run; do not recreate or revoke the certificate unnecessarily.

Xcode Settings > Components confirmed the iOS26.2 + iOS26.3.1 Simulator package is missing despite installed SDK files and an older Simulator runtime. Started its official Apple download (displayed 8.39GB); latest observed progress 36 percent. Wait for observed installation and changed destination eligibility before another provision attempt. Preserve both original failed logs; they were copied before any retry.

Current output/evidence: /private/var/folders/40/pkx1ymn10_s42501bl5799wh0000gn/T/chess-phone-signing-js8mq6y8/ (evidence/journal.json, attempt1-provision.log, attempt1-provision2.log, preflight logs, selected-device-state.json). The standalone evidence/validate_profile.py will verify actual profile bytes, team/app/device/certificate bindings, expiry, entitlements and full prepared app resources before signing. Independently verify installed-app inventory before install; the kit conflates inventory failure with absence and only warns on certificate/profile mismatch. Treat those as blockers yourself. Use a fresh signing output, preserve the unsigned original and do not proceed on an uncertain outcome. Keep the same reviewed kit and output directory for subsequent steps.

Goal: finish profile provisioning, then verify/sign/install/launch the private offline app, checking each stage. Text-only scope; camera, microphone, Bluetooth, glasses and audible output remain outside this operation. No commit was requested. No app code changed in this execution.


## Active task packet — phone installed and user-confirmed opening; next is phone UI acceptance (November 15, 2026)

All five signing-kit stages completed. Certificate created under the explicitly approved Personal Team Peter Munzon (FBYX5879MJ); official missing iOS platform component installed; exact phone became eligible; phone-specific profile created and 40 checks passed; signed copy passed 29 checks; original preserved. Chess Companion 0.1.0 build1 is installed on actual iPhone17/iOS27.2. Initial launch security denial was followed by user-confirmed developer trust and accepted launch. Alex confirmed the app opens and stays open, then said he closed/swiped it away. Do not misdiagnose the later missing process as a crash or claim a positive process snapshot. The top-level filename crash query is limited evidence.

Stable private artifacts/evidence: /Users/alexmunzon/chess-builds/iphone-2026-11-15/ (README.md, artifact-index.json, unsigned/ChessCompanion.app, signing/ChessCompanion.app, signing/profile.mobileprovision, signing/entitlements.plist and evidence/). No private key copied. Exact temporary command logs remain at /private/var/folders/40/pkx1ymn10_s42501bl5799wh0000gn/T/chess-phone-signing-js8mq6y8/. Profile expires November22 at15:22 Europe/Madrid. See docs/PHONE_INSTALLATION.md.

Next goal: actual phone offline-study UI/recognition/engine acceptance and measured responsiveness; preserve explicit review, uncertainty and invalidation gates. Installed/opening does not establish full engine behavior on phone. Existing exact in-flight switch UI timing gap remains separate from the passing held-reply mock. No glasses/camera/microphone/Bluetooth or audible speech approval was added. No commit requested or made, no app source changed. Avoid another certificate, provisioning or install attempt merely because Alex manually closed the app.


## Checkpoint — self-test mode, first real-phone engine evidence, replay groundwork (November 15, 2026, later)

**Self-test build.** `native/ChessCompanionApp/SelfTest.swift` is compiled only with `prepare_app.py --self-test` (`-D COMPANION_SELFTEST`) and runs only with launch argument `--chess-self-test`. It drives the same model methods as the buttons, with scripted review labelled as not human, a pass-through timestamp recorder around the real backend, and a silent speech stand-in (0 speak requests). A normal build contains no self-test symbols. Simulator: 12/12 on two runs; the first cold run was 11/12 because the first analysis exceeded the search deadline after 3.9 s (no recommendation shown). Evidence: `/Users/alexmunzon/chess-builds/selftest-2026-11-15/`.

**Real iPhone 17 / iOS 27.2, run 1 (`phone-run1/selftest-report.json`, SHA-256 `e6393012…ea2f7c2`).** All four playable fixtures completed recognition → scripted review → rules validation → Stockfish → legal text on the phone: `e2e4`, `e7e5`, `e1d2`, `a7a8q`. Recognition 1.74–1.79 s, validation 22–36 ms, analysis 1.57–1.72 s, engine start 0.62 s. At 17.1 s the app was deactivated (screen sleep is the likely cause, not established); the engine closed and status became "Paused…", so the remaining checks reported "engine not ready". That is one real deactivation revoking state on the phone, not a pass of the scripted safety checks. Run 2 (`phone-run2/`), after adding keep-awake and app-state logging, was deactivated 0.1 s after becoming active and backgrounded at 2.6 s: 0/10, no engine evidence. **Not yet observed on the phone:** obstruction blocking, four-of-five review, invalid FEN, untick revocation, in-flight switch, reset. These need the phone screen awake when the self-test is launched. The self-test build (signed executable `29f141fe…26a417`) is what is installed on the phone now.

**Read-only safety review.** No high or medium finding; every async reply is revision/token guarded. Two low items (sample-FEN checkbox wording; `ready` staying true after runtime self-close) and about ten untested late-reply paths are assigned to a mock-check packet.

**Replay groundwork (not yet in the app).** `scripts/simulation/select-replay-sequence.mjs` + `tests/replay-sequence.test.js` (14-frame dev-opening game plus occlusion frame; 960/960 Swift-vs-Python square agreement; no special moves in the image sequence). `src/core/replay-runtime.js` + `tests/replay-runtime.test.js` + golden transcript (11-ply game with en passant, capture, both castles; synthetic observations). `native/ChessCompanionIntegration/ReplayTracker.swift` + checks (94/94 on Mac, iOS typecheck, 28/28 cross-language). Contracts: `docs/REPLAY_GAME.md`, `docs/REPLAY_TRACKER_SWIFT.md`, `docs/REPLAY_SEQUENCE.md`. In progress: bundling the tracker into the WebKit runtime (changes the 12-asset bundle, so `prepare_app.py`/`AppAdapters.swift` pins must follow) and the app's Replay mode.

`npm test`: 181 tests, 179 pass, 0 fail, 2 opt-in skipped. No commit, push or distribution. No camera, microphone, Bluetooth, glasses or audio.


## Checkpoint — real-phone self-test 12/12 (November 15, 2026, 16:09 Madrid)

With the phone awake, `phone-run4/selftest-report.json` (SHA-256 `43679b46…a6b9c6`, `/Users/alexmunzon/chess-builds/selftest-2026-11-15/`) completed on the actual iPhone 17 / iOS 27.2: **12/12 checks, not incomplete, 0 speak requests, no app deactivation events**. Run 3 was a failed launch (CoreDevice error 10004, no process) and produced no new report; runs 1–2 are described above. All review in these runs is the scripted fixture, not human review.

- Four playable fixtures: `e2e4`, `e7e5`, `e1d2`, `a7a8q`. Recognition 1.62–1.83 s, validation 12–58 ms, analysis 1.50–1.69 s, engine start 0.33–0.42 s.
- Obstructed board blocked; four-of-five review blocked validation; side-to-move `x` rejected; unticking a review box revoked the recommendation; reset cleared; background handler revoked (handler invoked in-process, not real backgrounding; a real deactivation closing the engine was separately seen in run 1).
- **In-flight switch, first observation outside a mock:** analysis began at 27,686 ms, the fixture switch came 211 ms after the analyze call with the search still running, the backend call ended `cancelled` 20 ms later, and no recommendation or move was ever set during the 3,000 ms window; the next position then analyzed normally (`e7e5`). This is in-app event ordering on the phone via the self-test, not finger-driven UI timing, and whether the JS engine emitted a late message after cancellation is not visible from Swift.

**Mock safety suite now 28/28** (was 10/10): 18 new held-reply checks covering late analysis/validation/recognition/legal-text replies after edit, untick, reset, background and switch; terminal position; hash mismatch; wrong frame/revision; speech cancel on background; runtime self-close. No app bug was found by them. Review checkbox wording changed from "I supplied…" to "I checked and confirm…". The model now drops `ready` when the backend reports it closed; `NativeEngineRuntime.swift` still needs an `onClose` hook for that signal to fire immediately. `npm test`: 184 pass, 0 fail, 2 opt-in skipped (agent-reported; re-run pending after the runtime bundling packet lands).

The phone currently has the **self-test build** installed (built before the wording/closure changes). A normal build must be rebuilt, signed and reinstalled once the runtime bundle pins are updated.


## Checkpoint — 15-asset runtime integrated, proven on phone, normal app reinstalled (November 15, 2026, 16:25 Madrid)

The replay tracker is bundled into the local WebKit runtime (12 → 15 assets, manifest `4faa4b24…5525`); `runtime.js` routes tracker kinds (`mode:"trusted-replay"`) to one `ReplayRuntime` and everything else to `DeviceBackend`; `NativeEngineRuntime.swift` accepts the new kinds/assets and has an `onClose` hook that `LocalOfflineBackend` uses so the model drops `ready` when the runtime stops. `prepare_app.py` pins the three new assets. Evidence: `/Users/alexmunzon/chess-builds/replay-wiring-2026-11-15/` and `/Users/alexmunzon/chess-builds/integration-2026-11-15/`.

- Node: bundle test 5/5 (28 golden steps byte-identical through the built router); `npm test` 186 tests, 184 pass, 0 fail, 2 opt-in skipped (orchestrator re-run).
- Mac: integration checks 18/18; mock safety suite 28/28.
- Simulator, first real-WebKit execution of the new bundle: self-test 12/12 on three runs; analysis 1.8–4.1 s (one 4.13 s promotion search), no timeouts.
- **Real iPhone 17 / iOS 27.2, new self-test build** (`integration-2026-11-15/phone-run1/selftest-report.json`, SHA-256 `42f92f62…6bbd87`): 12/12, complete, 0 speak requests, no deactivation. Moves `e2e4`, `e7e5`, `e1d2`, `a7a8q`; recognition 1.53–1.82 s, analysis 1.47–1.84 s, engine start 0.26–0.43 s. Review is the scripted fixture.
- **The phone now has the normal build** from the current source (signed executable `625ab005…f110db`, unsigned `1139f1c0…05f187`, 0 self-test strings), launched once and seen in the process list. It includes the "I checked and confirm…" wording. It has not been hand-tested.

Not exercised anywhere real: the `onClose` path (no check kills the WebKit process); tracker requests through WebKit (routing is in the bundle but the app does not call it yet). In progress: the app's Replay mode (`ReplayGame.swift`), the first caller of the tracker in the app. Still no commit, push, distribution, camera, microphone, Bluetooth, glasses or audio.


## STOPPING POINT — November 15, 2026, evening (phone being disconnected)

**Phone state.** iPhone 17 / iOS 27.2 has the **normal** build installed (signed executable `625ab005…f110db`, no self-test code, "I checked and confirm…" wording), launched once, never hand-tested. Signing profile expires **November 22, 15:22 Madrid**; renew with `native/ChessCompanionApp/signing/renew_profile.sh`, then re-sign and reinstall. No phone action is pending; nothing below needs the phone until the Replay build is ready to run on it.

**Landed and checked today (see earlier checkpoints for evidence paths).**
- Self-test mode; real-phone 12/12 twice (12-asset and 15-asset runtime), including the first in-flight switch observation outside a mock. Review in those runs is scripted.
- Mock safety suite 10 → 28; two low review items fixed; `onClose` hook.
- Tracker bundled into the WebKit runtime (15 assets) with Swift client and transport; Simulator 12/12 ×3.
- Image sequences: 14-frame opening and a 25-ply special-move game (en passant, promotion, both castlings, captures; 1,792/1,792 Swift-vs-Python squares; tracker follows all 26 positions) — `docs/SPECIAL_GAME_SEQUENCE.md`, opt-in test `SPECIAL_GAME_DIR`.
- Move-level inference prototype: `src/core/occupancy-move-inference.js`; 159,235 plies, 99.36% unique and correct, 0 wrong, all ambiguity is promotion piece choice; one misread square always rejected; two misreads can fool it (unmeasured) — `docs/OCCUPANCY_INFERENCE.md`.
- Research: `docs/RECOGNITION_RESEARCH.md` (screen board + three-way occupancy first), `docs/GLASSES_SDK_RESEARCH.md` (Gen 1 supported; frame timestamps are on the glasses' clock with no documented phone-clock mapping; open issue where streaming pauses phone audio; Mock Device Kit available), `docs/LICENCE_AUDIT.md` (nothing to fix for private use; sharing needs an engine source pack).
- Independent review of today's code: no high/medium. Fixed in `sign_and_install.sh`: `..` path bypass, identity matching, certificate-not-in-profile now fatal, re-hash and bundle-id check of the signed copy; provisioning file types added to `.gitignore`.
- `signing/phone_selftest.sh`, `renew_profile.sh`, `summarize_selftest.py`: dry-tested only; first real use will be the Replay build.

**Open low items from the review (do after the Replay agent finishes, they touch its files).** `Number.isSafeInteger` for `capturedAtMs` in `src/core/replay-runtime.js` (then rebuild bundle + re-pin); `if !runtime.isReady { runtimeStopped() }` after start in `AppAdapters.swift`; stale "12 assets" line in `docs/REPLAY_GAME.md`; `tests/replay-runtime-bundle.test.js` needs a call-count assertion and coverage of the reply-posting path.

**Still running when this was written (results will be appended below when they report; none may touch the phone or commit).**
1. App Replay mode (`native/ChessCompanionApp/ReplayGame.swift` etc.) — must pass mock checks and two Simulator self-test runs; outputs in `/Users/alexmunzon/chess-builds/replay-mode-2026-11-15/`.
2. Occupancy pixel classifier prototype (`scripts/recognition/occupancy_classifier.py`, `docs/OCCUPANCY_CLASSIFIER.md`).
3. Screen board detection prototype (`native/ScreenBoardVision/`, `scripts/recognition/make_screen_scenes.py`).
4. Recognizer speed-up, delivered as patches in `/Users/alexmunzon/chess-builds/recognizer-perf-2026-11-15/` (not applied).

**Next packets, in order.** (a) Review Replay; apply the open low items; run Replay self-test on the phone with `phone_selftest.sh` (needs phone connected, awake). (b) Apply and verify the recognizer speed patch; measure on phone. (c) Swap the bundled replay game for the special-move game. (d) Wire occupancy inference + pixel classifier + screen detection into one offline "screen board" pipeline on simulated scenes. (e) Mock Device Kit capture path in the Simulator. (f) Refresh the status artifact.

**Decisions waiting on Alex.** Local git checkpoint commit (about 100 uncommitted files; nothing is committed, pushed or distributed). Camera/glasses approval for the first screen-board capture experiment. Whether to download the non-commercial ChessReD dataset (about 29 GB) for the physical-board path.


## Checkpoint — Replay game mode 18/18 on the real phone (November 15, 2026, 21:40 Madrid)

Local commit `a13ed1c` holds everything up to the stopping point. After it: Replay mode finished, screen-board detection finished, review fixes to the signing kit. These are uncommitted.

**Replay mode** (`native/ChessCompanionApp/ReplayGame.swift`, `ReplayGameChecks.swift`; mode picker in `ChessCompanionApp.swift`; 14 main frames + 1 occlusion frame pinned in `prepare_app.py`; no manifest or evaluator truth bundled). Mock suite 21/21 with four mutation-failure proofs; existing mock suite 28/28. Simulator self-test (18 checks) on a heavily loaded Mac: 15/18, 17/18, 17/18, 17/18 — all failures were engine deadlines under load (cold-start analysis, and the strict full-game check), none showed anything stale. Evidence: `/Users/alexmunzon/chess-builds/replay-mode-2026-11-15/`.

**Real iPhone 17 / iOS 27.2** — first real use of `signing/phone_selftest.sh` (sign → install → run → fetch → summarize → restore): `phone-run1/selftest-report.json`, SHA-256 `90003729…e79be0`, **18/18, complete, 0 speak requests, exit 0**.
- Study checks 12/12 as before (recognition 1.44–1.69 s, analysis 1.47–1.61 s).
- Replay: no analysis before review; after one scripted review the bundled tracker (inside WebKit, first execution on the phone) followed all 14 frames through real native recognition: e4, e5, Nf3, Nc6, Bc4, Nf6. Legal text recommendations at 7 plies (`e2e4 e7e5 g1f3 b8c6 f1b5 f8c5 d2d3`), each legal per the app's own rules reply and bound to (run, epoch, revision, FEN); engine search 1.46–1.62 s; a frame step 1.57–1.67 s (two tracker requests each).
- Inserted obstructed frame: 16 unknown squares → tracking and recommendation revoked, next good frame stayed in needs-review with 0 tracker requests until a renewed (scripted) review, then tracking resumed (review epoch 2).
- Stepping during analysis showed nothing stale; tracker and engine never overlapped; leaving the mode revoked.
- Review in all of this is the scripted fixture. No human has used the Replay screen.

**Phone now has the normal build with Replay mode** (unsigned `e554c369…8e3c02`, signed `ca2f47cf…9a1820`, verified free of self-test strings before install). Not hand-tested.

**Screen-board detection prototype** (`native/ScreenBoardVision/`, `scripts/recognition/make_screen_scenes.py`): on 360 simulated screen scenes it found the board within 1% in 99.5% (dev) / 99.3% (held-out), 0 false accepts including 48 non-board negatives, mean corner error about 0.12 px, about 100 ms per frame on the Mac; iOS typecheck only. Simulated flat screens without lens distortion or moiré; one piece set. Agent-reported, not re-run.

**Still running:** occupancy pixel classifier; recognizer speed-up patch. **Still open:** the low review items listed at the stopping point; recognition at about 1.5 s per frame on the phone is the main speed limit for following a game.


## Checkpoint — optimization flag found and applied; phone run interrupted (November 15, 2026, 22:15 Madrid)

**Cause of slow recognition:** `prepare_app.py` compiled the app with no `-O` (Swift default `-Onone`). Mac, same code: about 3,000 ms per frame at `-Onone`, 41 ms at `-O`, about 27 ms with the patched Vision sources. Full report: `docs/RECOGNIZER_PERFORMANCE.md`; evidence `/Users/alexmunzon/chess-builds/recognizer-perf-2026-11-15/`.

**Applied (uncommitted, on top of `1e34c5c`):** `recognizer-perf.patch` (Vision), `app-side.patch` (recognizer prepared once in its actor; `-O` in `prepare_app.py`); a `SelfTest.swift` helper made static for the Swift 6 data-race check at `-O`; `capturedAtMs` must be a safe integer in `replay-runtime.js` and `device-game-session.js` (the latter went beyond the brief: without it a `1e300` frame left the tracker stuck until the next review; golden transcript unchanged); `start()` reports a runtime that died during start; stronger `replay-runtime-bundle` tests; doc line. Runtime manifest is now `d2e2c51d…e84d44`.

**Checks (integration agent; `npm test` re-run by orchestrator: 204 tests, 200 pass, 0 fail, 4 skipped):** decisions byte-identical before/after on 78 frames / 4,992 squares and 15 frames / 960 squares; mock suites 28/28, 21/21, 18/18, 94/94; Simulator self-test 18/18 ×3 at load 3–9; in-flight switch and step-during-analysis still caught a running analysis. Simulator recognition 2,975–3,479 ms → 51–129 ms; replay step 2,791–3,454 ms → 36–96 ms; engine search unchanged. Evidence: `/Users/alexmunzon/chess-builds/perf-integration-2026-11-15/`.

**Phone:** `phone_selftest.sh` run 1 with the optimized self-test build was **INTERRUPTED (exit 3)**: the app started inactive (`applicationState 1`), all 7 attempted checks reported "engine not ready"; no timing evidence. The script then restored the **optimized normal build** (unsigned `5c9ce79e…17745d`, signed `4d43ca0d…0ddf0c`, 0 self-test strings), which is what the phone has now. Optimized recognition speed on the phone is still unmeasured. Re-run needs the phone awake and unlocked.


## Checkpoint — optimized build 18/18 on the real phone (November 15, 2026, 22:18 Madrid)

`perf-integration-2026-11-15/phone-run2/selftest-report.json` (SHA-256 `e513d3ca…92677c`), iPhone 17 / iOS 27.2, optimized self-test build (unsigned `064f454c…41309d`): **18/18, complete, 0 speak requests, exit 0**, app active throughout.

- **Recognition on the phone: 39–122 ms** per image (was 1,440–1,830 ms unoptimized). Replay frame step (recognition + two tracker requests): **52–88 ms** (was 1,570–1,670 ms).
- Engine search unchanged: 1.50–1.99 s, with one 3.46 s search (after-e4 fixture). The engine is now the dominant cost.
- Moves this run: study `e2e4`, `c7c5`, `e1d2`, `e1d2`; replay `e2e4 e7e5 g1f3 b8c6 f1b5 g8f6 d2d3`. Moves vary between runs (bounded search); each was accepted by the app's own rules reply.
- All safety checks passed again, including in-flight switch and step-during-analysis. Review is the scripted fixture.

Phone now has the **optimized normal build** (unsigned `5c9ce79e…17745d`, signed `4d43ca0d…0ddf0c`, 0 self-test strings, Replay mode included). Not hand-tested. All of this is uncommitted on top of `1e34c5c`.

**Next:** join screen detection + occupancy classifier + move inference into one offline pipeline on simulated scenes; swap in the special-move replay game; Mock Device Kit capture path; decide on the engine search budget now that recognition is no longer the bottleneck.


## Active packet — 2026-11-17 ChatGPT build sprint

Goal: finish scoped safety fixes and make public repository documentation accurate and usable. User clarified GitHub code quality is priority, not a visual demo.

Owned changes: guard builder (guard, guard tests/docs), runtime builder (NativeEngineRuntime, TrackerGateChecks, check-native), corner builder (pipeline default/tests/docs), documentation worker (README/PLAN/VERIFICATION/engine doc). Parent integrates only after fresh review. Detailed live checkpoint: /Users/alexmunzon/Documents/Codex/2026-11-17/pr/work/session/CHECKPOINT.md.

Constraints: no app tracker or piece guard activation; no held-out reuse, camera, audio or glasses; no new commit/push in this packet. Repository visibility is now PUBLIC, confirmed in GitHub after explicit user approval. Historical references to private repository describe prior state. User switched work to ChatGPT; old Claude usage/model instructions no longer describe this session.

Baseline evidence: parent check-all 11/11 before guard restoration; native26/26 with known duplicate-kind gap; restored round7 guard32/32. Interrupted round8 files preserved in workspace before restoration. Builders now work on fresh fixes. Acceptance: old-code failures and mutation checks for new guard/runtime properties, fresh independent review each fix round, parent rerun key checks and final full check. Stop condition: tested/reviewed bounded changes or genuine unmet dependency; record unverified cases explicitly.


## Completed ChatGPT packet — 2026-11-17T17:18:29+01:00

Final combined checks 12/12 on frozen reviewed source; phone 34/34, normal restored. All workers checkpointed, no jobs running. Full completed record: SESSION-HANDOFF-2026-11-17.md. Parent verified source fingerprints before publication. User explicitly requested push all progress after tests; publication follows this checkpoint. No held-out data reused. Remaining research and permissions are recorded in the session handoff.
