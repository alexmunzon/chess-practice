# Experimental whole-photo Core ML recognition

Private noncommercial evaluation only. No model weights, source photographs, or derivatives are included in the repository. No hardware, camera permissions, uploads, accounts, or dependencies were added. The saved-photo API and draft-review UI use this evaluator; it is not eligible for automatic guidance. No end-to-end real-photo browser success or audible speech test is established.

Model: joelseytre/chessq-lite at immutable revision `7b33e1d47be02ce67b8e30ff7f09418166037d99`, `cq-vit-s-644-v4-seed2-coreml-fp16-r1`. Model ZIP SHA-256 `091e8a9f22a517322eccd7bf8292a76fd653f9f913ff15d2eb9e8d914e959016`, 62,465,224 bytes. Reference ZIP SHA-256 `aaa3ab7f2b119bacfb5596b3387a9082e726fd9d8b378019836f150eb097da0b`, 8,871,142 bytes. Both verified before traversal/symlink-checked extraction. License is PolyForm Noncommercial 1.0.0, with DINOv2 Apache notices, retained beside downloaded model. No upstream code was executed. Do not redistribute weights or assume commercial rights.

Source documentation: https://huggingface.co/joelseytre/chessq-lite/blob/7b33e1d47be02ce67b8e30ff7f09418166037d99/COREML.md

## Reproduce

External root: `/Users/alexmunzon/Library/Developer/ChessCompanionEvaluation`.

Compile `swiftc native/PhotoRecognition/RunModel.swift -o "$ROOT/models/chessq-lite/run-model"`, then `python3 tests/recognition_whole.py "$ROOT"`. Existing NumPy/Pillow and Apple CoreML are used. Results reside under `$ROOT/results/whole-photo`. The runner takes package path followed by pairs of raw little-endian float32 tensor input and JSON output paths. It compiles/loads once, then performs three predictions per input. All use CPU_AND_GPU; prediction times exclude preprocessing and compile/load. Only last-pass logits are retained.

Preprocessing applies EXIF once, decodes RGB, independently resizes floating-point channels with Pillow antialiased bilinear to 644×644, and applies ImageNet normalization to NCHW float32. No crop, pad, corners, orientation annotation, labels, or state enter inference. Preprocessing has not been numerically compared to the training implementation. Outputs use first-index argmax, class order `.PNBRQKpnbrqk`, a8..h1. Fixed .95 softmax threshold is not calibrated confidence. No king repair or chess-rule repair. Proposal files always require review, contain placement only, set FEN null and guidanceAllowed false.

## November 10 diagnostic results

- Development: 64/64 squares, 32/32 occupied, exact board, 64 accepted, zero accepted wrong.
- Previously used heldout-1: 64/64 squares, 32/32 occupied, exact board, 64 accepted, zero accepted wrong.
- Previously used heldout-2: 57/64 squares, 30/32 occupied, not exact, 60 accepted, **3 accepted wrong**.
- Aggregate: 2/3 raw and accepted exact boards, 185/192 squares (96.35%), 94/96 occupied (97.92%), coverage 188/192 (97.92%).
- Warm photo inference 150.05–165.51 ms, preprocessing 114.70–387.53 ms. Compile/load 837.37 ms. First inference was on synthetic reference 0 and took 3,218.50 ms, not included in warm photo timings. These are one Mac run, not phone or glasses latency.
- **Numerical validation FAILED** the preset reference tolerance: all 192 argmax labels matched, but 1/2,496 logits exceeded `0.01 + 0.001*abs(expected)`. Maximum absolute error .02641249. Failure: synthetic case 0, square index 48, class 0; expected 6.85546875, actual 6.82905626, allowed error .01685547. Do not relax the tolerance after observing results or claim successful validation. As of November 11, the diagnostic preserves its report and exits 1 when this numerical gate fails; earlier invocations could exit 0 despite a failed report. The exit-status regression does not rerun inference or resolve numerical drift.

Three starting-position photos are a tiny cross-model diagnostic, not untouched future holdout or general recognition accuracy. Training-source overlap is unknown. No thresholds were tuned to these labels. Further reference-drift investigation, varied independent positions, occlusions, confidence calibration, temporal integration, and human review remain required.

## Numerical follow-up

November 11 bounded diagnosis: see `docs/NUMERICAL_DIAGNOSIS.md` for the latest results. Artifact/input/layout checks found no error explaining the original failure. A separate one-plus-three-pass diagnostic had 33/2,496 failing logits on every pass, with identical outputs across passes; the unchanged executable reproduced the current case-0 output exactly. Current runtime/backend behavior differs from historical output, and exact cause remains unresolved. The gate stays failed, and no optimized runner was adopted. The diagnostic harness now sanitizes its inherited CPU-only flag and verifies native configuration metadata before reporting CPU_AND_GPU.

The outlier was reproduced once with `allowLowPrecisionAccumulationOnGPU = false` explicitly set. CPU_AND_GPU returned the identical outlier (6.82905626297) and one failing logit on case 0; 64/64 labels still matched. Separate CPU_ONLY_DIAGNOSTIC on case 0 produced 716/832 logits outside tolerance, max error .48571777, although 64/64 labels matched. CPU-only is a different execution profile and does not validate the required CPU_AND_GPU path. Set `CHESS_COREML_CPU_DIAGNOSTIC=1` only for this diagnostic. The normal runner explicitly disables low-precision GPU accumulation.

Regression checks: npm test 55/55 passed. Existing calibration test passed manual checks, five synthetic positive detections and two negative rejections on the concurrent current calibration implementation. Decode checks rejected malformed/nonfinite logits and preserved first-class ties as unknown at uniform softmax.

## Genuine-video partial-label diagnostic

Run `python3 scripts/recognition/evaluate_video.py "$ROOT"`; scorer regression tests: `python3 tests/recognition_video.py`. The existing preprocessing and .95 threshold were frozen/hash-recorded before inference. Source video and five frame hashes were verified. Predictions and freeze record are under `$ROOT/results/video-whole-photo`; sanitized report is `native/PhotoRecognition/video-results.json`. No media is shipped.

The five preselected 0/4/8/12/16-second frames are one correlated Pexels video (Tima Miroshnichenko, 6599638), not five independent games. Independently annotated printed coordinates intentionally do not assume ordinary piece placement. Raw model outputs are scored literally a8..h1, without geometry or orientation annotation entering inference. A separately named manual-annotation-rotation-control rotates each entire image counterclockwise 90 degrees based solely on the printed-coordinate mapping; it is not automatic recognition performance. No crop/perspective adjustment or post-hoc orientation search was performed.

Raw whole-photo result:
- 122/262 known labels correct (46.56%); 0/74 known occupied piece labels correct, while accepting 70/74 (94.59% occupied-type prediction coverage).
- 120 wrong among 236 accepted known labels (50.85% accepted-wrong rate).
- 142/287 known occupancy labels correct; detected occupied on 20/99 known-occupied cells. 66/188 known-empty cells predicted occupied, including 50 accepted false positives.
- Overall prediction acceptance 282/320 (88.13%). Unknown piece-label ground truth: 58 cells, 46 accepted. Unknown occupancy/occluded ground truth: 33 cells, 31 accepted. These last values quantify asserted certainty, **not accuracy**.
- Manual rotation control: 138/262 known labels correct, 1/74 occupied types correct, 85/211 accepted known labels wrong; 27/33 unknown-occupancy cells accepted. This does not rescue the result and does not count as automatic performance.

The scores include coordinate correspondence errors and do not separate orientation failure from semantic piece-classification failure. No best-fit coordinate rotation was selected after viewing predictions. They establish that current output cannot be trusted as canonical board state, not that the model internally failed every occupied-piece classification.

First raw inference 340.97 ms, subsequent raw predictions 144.08–208.36 ms, compile/load 687.28 ms; preprocessing over both profiles 102.69–224.53 ms. This run benefits from an existing machine cache and does not replace the earlier 3.2-second uncached first-inference measurement. Manual-control preparation additionally includes rotated-image encoding. Three predictions per frame, last logits scored. No hardware/phone/glasses/live timing claim.

No exact-board accuracy or full FEN is available: decorative major-piece labels and occluded squares remain unknown. Five scorer tests verify exclusions, known occupancy with unknown type, abstention, accepted wrong labels and missing-square rejection. The previous numerical-validation failure remains an unresolved gate. Human-confirmed complete state, larger independent data, coordinate handling, calibrated abstention, temporal/lifecycle integration and physical device validation remain necessary; guidance is always false in this diagnostic.

## Fixed manual-localization controls

Reproduce with `python3 scripts/recognition/evaluate_video_controls.py "$ROOT"`; transform tests with `python3 tests/recognition_video_controls.py`. Separate reports reside in `native/PhotoRecognition/video-control-results.json` and `$ROOT/results/video-manual-controls/report.json`; original raw results remain unchanged.

Two additional controls were fixed before observing their predictions: (1) the axis-aligned bounding box of the annotated screen corners, expanded by 10% of board width/height on each side, clipped to the image, then rotated counterclockwise 90 degrees; (2) existing cstr ONNX classifier using annotated canonical a8/h8/h1/a1 corners and `white-bottom` solely to disable output-index inversion. Neither means that the staged pieces follow normal colors or legal setup. Neither is automatic localization, and neither counts toward automatic performance. No variants were searched or thresholds changed.

- CoreML crop control: 116/262 known labels correct (44.27%), 0/74 known occupied types correct, 73/74 occupied-type predictions accepted; 130/238 accepted known labels wrong (54.62%). Known occupancy correct 137/287; 72/188 empty false positives, 57 accepted. All 33 unknown-occupancy cells accepted, which is certainty without accuracy ground truth.
- cstr canonical-corner control: 191/262 known labels correct (72.90%), 7/74 occupied types correct (9.46%). Only 15/74 occupied-type predictions accepted, and none of those 15 correct. Known occupancy correct 256/287 (89.20%), with occupied detected on 72/99 known occupied cells. Empty false positives 4/188, none accepted. Accepted known labels wrong 15/189 (7.94%); this lower rate includes many easy empty cells and does not establish dependable piece recognition. Unknown-occupancy cells accepted 16/33, not scored for accuracy.

CoreML control compile/load 670.93 ms; first prediction 271.14 ms; subsequent predictions 143.78–161.78 ms. cstr model load 436.93 ms, crop-plus-inference 417.83–438.52 ms per frame. These are cached-machine diagnostic runs, not on-device/live performance.

The fixed crop does not fix CoreML's canonical-state failure. Annotated canonical geometry improves cstr occupancy but piece-type classification remains unusable at this threshold. Coordinate assumptions and semantic classification are still confounded for whole-photo predictions; no best-fit remapping was performed. Actual live guidance remains blocked by trusted localization/orientation, reliable occupied-piece recognition, calibrated abstention for hands/occlusion, complete human-confirmed historical state and physical-device validation. The existing CoreML numerical gate also remains unresolved.

Four transform tests passed: exact fixed margin, boundary clipping, canonical perspective corner mapping, and CCW source-top-right to output-top-left mapping. Five partial-label scorer tests passed. No additional inference was run during this verification after reconnecting the Mac.
