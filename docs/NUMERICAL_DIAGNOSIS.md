# CoreML parity diagnosis — November 11, 2026

**The numerical gate remains failed.** The latest authorized comparison, with an Apple M1 visible to Metal, reproduced the historical outputs exactly: **1/2,496 logits outside the unchanged tolerance**, with 192/192 matching argmax labels. The earlier restricted run's larger 33-logit discrepancy is retained separately below. No stale artifact, normalization, tensor layout, class-order, output-indexing or tolerance-arithmetic bug was demonstrated as the remaining outlier's cause. Actual per-operation compute placement was not observed. This is separate from the already failed real-video accuracy gate.

## Identities and the original failure

The model ZIP (`091e8a9f…959016`), reference ZIP (`aaa3ab7f…97da0b`), extracted package members, reference inputs, target metadata and target arrays match their pinned hashes and archives. All three saved reference tensors byte-match the published normalized float32 inputs. The old development photo was preprocessed again with the unchanged code and byte-matched its saved tensor. No original model, runner, input, target or historical result was replaced.

The reference array has three CHW cases; each is loaded into `[1,3,644,644]` float32 NCHW. Outputs stack to `[3,1,64,13]`, matching targets without broadcasting. Class symbols `.PNBRQKpnbrqk` and a8..h1 order match the local manifest. FP16 describes the target execution recipe; target arrays are stored as float32. Synthetic inputs bypass photo decoding, EXIF, resize and normalization, so differences in Pillow photo preprocessing cannot explain their failure. Photo preprocessing equivalence to upstream is still a separate unvalidated question.

The historical result still has **1/2,496 logits outside** `abs(error) <= 0.01 + 0.001 * abs(expected)` and 192/192 matching argmax labels. The failing element is case 0, square 48 (a2), class 0 (empty): expected **6.85546875**, observed **6.829056262969971**, error **0.026412487030029297**, permitted **0.01685546875**. Recomputing in float64 or float32 preserves the failure. A historical explicit-low-precision-disabled repeat has identical logits. Choosing FP32 targets instead also fails that location; no target substitution is justified.

The apparent target checksum difference is explained by distinct files: release hash `6514b370…bc5a7` identifies `targets.json`; its `arrays_sha256` value `900e3bf1…1685a` identifies `logits.npz`. Both match. Source/retrieval/distribution revision labels differ, but the actual archive and member identities match.

## Earlier restricted versioned native diagnostic

`RunParityV1.swift`, preserved in the session outputs, compiles and loads the same package once with requested `CPU_AND_GPU` and `allowLowPrecisionAccumulationOnGPU:false`. For each of the three synthetic references and one old development photo it makes one prediction, followed by the existing three-pass sequence on that same loaded model. It retains every pass rather than only the third. This copy is not part of the review/production path.

Input strides were `[1244208,414736,644,1]`; output strides were `[832,13,1]`. Input bytes remained unchanged after each prediction. All 832 linear output reads exactly equaled coordinate-based reads. All four passes for each input were numerically identical.

Reference comparison in this restricted run: **33/2,496 logits outside tolerance on every pass** (25 in case 0, zero in case 1, eight in case 2); maximum error **0.046875**; 192/192 matching labels. The comparison script preserved its report and exited **1**. The former historical outlier fell inside tolerance in that run, but other values failed; the old failure was preserved rather than overwritten or relabeled. The subsequent authorized comparison below recovered the historical outputs.

A separate control ran the **unchanged pinned executable** on exactly reference 0, writing only to a new output file. Its third-pass logits exactly match all four diagnostic passes, including the 25 current failures. This rules out the diagnostic instrumentation as the explanation for that input's current discrepancy. The new and historical outputs differ despite matching model/input identities.

Runtime evidence: macOS **15.7.4 (24G517)**, arm64, CoreML bundle **3405.2.1**, Swift **6.2.4**. The local upstream document reports a pass on M3 Pro/macOS 26.6.2; that upstream execution was not reproduced here. `MTLCreateSystemDefaultDevice()` returned nil in this restricted run. Requested compute units are **not** proof of per-operation GPU execution; no execution-device trace was obtained. The hardware-model query was denied and was not retried. These differences supported investigation of runtime/backend conditions, but did not prove a particular fallback or numerical cause. The later explicitly authorized invocation observed a Metal device without rerunning that denied query.

The first diagnostic invocation failed before inference because CoreML could not create its default temporary working directory (CoreML code 3, underlying Cocoa 513/POSIX EPERM). Its exact log is retained. A new invocation used a private directory under already writable `/tmp`, matching the existing photo bridge's explicit `TMPDIR` pattern. No permission changed; only newly created diagnostic temporary directories were removed. Package compilation happened for each invocation; compiled-file hashes are recorded, but lower-level system caches were neither cleared nor independently traced.

## Earlier restricted one-prediction versus three timing

| Input | One prediction (ms) | Following three predictions, total (ms) |
| --- | ---: | ---: |
| Synthetic reference 0 | 3,023.30 | 30,466.59 |
| Synthetic reference 1 | 8,838.27 | 10,034.48 |
| Synthetic reference 2 | 1,816.00 | 10,139.28 |
| Old development photo | 1,870.40 | 7,188.58 |

Shared compile/load was **1,467.99 ms**: compilation 185.18 ms and loading 1,282.81 ms. Fresh photo preprocessing separately took 127.65 ms. Predictions ranged from 1.816 to 23.048 seconds in this diagnostic; the unchanged executable control ranged from 1.737 to 3.237 seconds. Timings vary substantially. This is one ordered run with existing caches and uncontrolled system load, not a clean cold-cache, randomized performance experiment or phone/glasses benchmark. Prediction timings exclude output reading and preprocessing.

One pass gave exactly the same output as three for these four inputs, but neither configuration passed numerical validation. Even the fastest prediction in this restricted run exceeded the unchanged one-second frame-age limit. **No optimized runner was adopted**, no threshold or tolerance was changed, and automatic advice remains disabled. These timings do not describe the later authorized run below.

## Authorized GPU-visible comparison — latest result

The user explicitly approved one local comparison outside the restricted sandbox, using the same versioned diagnostic executable and the three immutable synthetic reference tensors. The executable SHA-256 was `e035b1d40dc2d9bc163acc482535e4f44cef34b81b861d61e038fbcd42d7c848`. It loaded one model and made one prediction followed by three further predictions for each input. The old development photo was **not included** in this follow-up. No network, camera or glasses operation was part of this comparison.

Metal reported **Apple M1** available. Requested compute units remained `CPU_AND_GPU`, with low-precision accumulation disabled; CoreML remained **3405.2.1** on macOS **15.7.4 (24G517)**. Device visibility does not establish where each model operation executed; that trace remains unavailable.

All four outputs per input were identical. Every aggregated pass exactly matched the historical logits and retained **1/2,496 failures**, at the same case 0 / a2 / empty element detailed above, with all **192 labels matching**. `numericalGatePassed` is **false**. The native invocation's exit 0 means predictions completed; it is not a numerical validation pass. Recovering the historical result supersedes the earlier claim that reproducing those outputs required finding a compatible environment. It does not fix the original outlier or prove its cause.

| Synthetic input | First prediction (ms) | Following three predictions, total (ms) |
| --- | ---: | ---: |
| Reference 0 | 406.45 | 483.91 |
| Reference 1 | 163.00 | 474.25 |
| Reference 2 | 158.40 | 480.03 |

Individual predictions ranged **152.88–406.45 ms**. Shared compilation and loading took **1,447.30 ms** (211.37 ms compilation; 1,235.93 ms loading); native total was 3,797.25 ms. These are one ordered desktop run with no cold-cache claim. They exclude photo decoding/preprocessing, live capture, queueing and speech, and do not establish end-to-end compliance with the one-second freshness guard. No persistent/single-pass production runner was adopted and no physical-board model was qualified.

Evidence: [authorized comparison](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/completion-build-2026-11-11/authorized-coreml-comparison.json), [invocation record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/completion-build-2026-11-11/authorized-coreml-invocation.json), and [runtime record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/completion-build-2026-11-11/authorized-coreml-v1/runtime.json). The earlier restricted evidence and original artifacts remain unchanged.

## Evidenced code correction and decision

The separate diagnostic harness `tests/recognition_whole.py` inherited `CHESS_COREML_CPU_DIAGNOSTIC`, while its report unconditionally claimed CPU_AND_GPU. It now removes that flag for the required profile and verifies every returned native record explicitly reports CPU_AND_GPU and low-precision accumulation disabled before scoring those exact records. This protects configuration provenance; it does not prove physical GPU execution and does not explain the historical CPU_AND_GPU outlier. The production photo bridge already sanitized this flag and was unchanged.

Focused regressions in the earlier restricted iteration: **5 numerical-report/profile tests**, **5 photo normalization/decoding tests**, and **42 review/processor/queue/live-session tests** passed. `git diff --check` passed. No HTTP, original Vision detector, downloads, installs, browser, SDK or device operation was run in that iteration. Later authorized SDK/download work is recorded separately; those earlier exclusions do not describe the whole continuation.

Decision: retain the failed numerical gate and existing runner. The approved GPU-visible comparison recovered the historical result but still failed the unchanged published target tolerance, so an environment capable of reproducing history is no longer an outstanding dependency. The residual outlier would need an evidence-supported upstream runtime/export investigation or demonstrated correction; there is currently no basis to change model weights, targets, preprocessing, tolerances or caches. Repeating the same comparison would not establish correctness. Real-board accuracy and real glasses performance remain independent gates. Immediate simulation work proceeds separately under [SIMULATION_PLAN.md](SIMULATION_PLAN.md), without claiming the physical-photo model is qualified.

Evidence is under the continuation session's `outputs/numerical-diagnosis-2026-11-11/`: original-file hashes, read-only audit, all native per-pass logits, runtime/compiled-artifact identities, pinned-runner control, `comparison.json`, focused test logs and versioned diagnostic source. Original external files and blackjack are checked unchanged in the final preservation record.
