# Paired geometry evaluation protocol

November 11, 2026. Purpose: isolate the contribution of board geometry using the **same occupancy and piece classifier** with (A) automatic corners and (B) independently annotated corners. This is an offline recognition experiment, not a camera-to-speech or glasses test. No new paired inference result is claimed here.

## Local inventory and eligibility

Media root: `/Users/alexmunzon/Library/Developer/ChessCompanionEvaluation`. Keep source media and derivatives outside the repository.

| Local source | Existing evidence | Eligibility for a new held-out comparison |
| --- | --- | --- |
| Staxringold development photograph | Used to develop geometry and evaluate both classifiers | Development only |
| `input/heldout-1.jpg`, `input/heldout-2.jpg` | Previously evaluated starting-position photographs; labels and corners exist | Historical held-out names do not make them fresh holdout data |
| Pexels 6599638, Tima Miroshnichenko | Five annotated frames already used for geometry, whole-photo and manual-corner classifier diagnostics | Reused diagnostic source; additional frames remain in the same source group |
| Pexels 6184294, Yaroslav Shuraev | Previously screened candidate; five existing frames independently inspected again without consulting corresponding predictions | Partial-board/occlusion diagnostic only; no eligible frozen corner/type-label set exists |

The candidate [A Chess Move](https://www.pexels.com/video/a-chess-move-6184294/) is locally 8.50 seconds, 24 fps, 2732×1440. Source SHA256: `9396030f775f4b59cb88777dbfcfd410be1e736d5e4f9267a4f333adede9b76c`. Existing frames at 0/2/4/6/8 seconds exactly matched fresh local ffmpeg decodes by SHA256. In those five inspected frames the near playing-surface corner is cropped, rear pieces have shallow focus and overlap, and hands obscure the board at 2/4 seconds. Some visible pieces could receive partial labels, but four independently visible corners and complete piece labels are unavailable. Do not extrapolate the missing corner and present it as observed ground truth. This assessment covers the inspected samples, not an exhaustive annotation of every video frame.

**No genuinely eligible, fresh, independently labeled held-out set is currently ready locally.** A distinct public source can be held out from this project's development, but upstream training-image overlap remains unknown. Available model provenance records do not provide a complete training-source exclusion list. No training non-overlap claim follows from a new filename, URL, author or source hash.

## Freeze before predictions

1. Maintain a source-split registry with source URL, author, license evidence, media SHA256, filming/session group, split, prior use and date. Keep all frames and derivatives from one source/session in one split. Record any known related shoots; unknown relatedness remains unknown. Reused sources are development/diagnostic, never relabeled as fresh holdout.
2. Choose timestamps and inclusion criteria before model results. Record frame index, timestamp, image SHA256, EXIF-oriented dimensions and visible-board coverage. For the main geometry comparison, require independently visible playing-surface corners. Retain rejected partial-board/occluded frames in a separately named abstention challenge; do not hide their exclusions.
3. Annotate without viewing either arm's predictions. Record each square's piece/color or `unknown`, independently known occupancy or `unknown`, and reason for uncertainty. Occluded, blurred or indistinguishable pieces stay unknown; do not recover them from starting-position assumptions, adjacent frames or legal-move repair. A second independent review should resolve disagreements or leave them unknown. Assistant estimates are not user confirmation.
4. Freeze image-order corners TL/TR/BR/BL, corner uncertainty and canonical a8/h8/h1/a1 correspondence using visible coordinate evidence. Store the explicit permutation from image-order to canonical-order corners. Any fixed image rotation must be chosen here, applied to both arms, and accompanied by the transformed corner mapping. Never choose a rotation/permutation by maximizing prediction accuracy or assuming piece colors indicate orientation. Reject unsupported/ambiguous orientation instead of guessing.
5. Save the annotation manifest and its SHA256 before inference. Freeze classifier weights/hashes, detector source and binary, preprocessing/crop code, scorer code, runtime versions, orientation policy and score threshold. Validate canonical output indexing with an asymmetric labeled fixture independent of evaluation predictions. Check upstream crop/normalization conventions; existing crop-shape tests alone do not establish numerical preprocessing equivalence.

## Run the paired comparison

Use the pinned cstr occupancy/piece model pair for both arms. Keep pixel decoding, image rotation, crop construction, normalization, class order, threshold and runtime identical. Only the supplied geometry differs. The whole-photo CoreML model is a separate experiment; substituting it for one arm would confound the comparison.

- **A — automatic geometry:** pass image pixels to the frozen detector without annotated corners or square labels. Apply only the previously frozen orientation mapping. A genuine no-candidate result is geometric abstention; do not substitute manual corners.
- **B — annotated geometry:** use the independently frozen corners and the same orientation mapping. Report corner uncertainty. This arm measures classification conditional on annotated geometry; it is not automatic end-to-end recognition.

Record runtime/permission/decoder/model failures as `execution-error`, separate from a successfully executed detector's `abstained` result. In particular, the current Apple Vision CVPixelBuffer failure cannot be counted as board-detection failure or replaced silently by another runtime/detector. A local CPU ONNX check on the reused 6599638 t00 frame succeeded (about 446 ms load, 510 ms inference; all 64 output labels/scores matched the previous result). That is a development runtime check only; automatic Vision inference was not retried and the A/B experiment remains unperformed on fresh data.

`replay_geometry_comparison.py` is the replay evaluator for recorded artifacts. Its report must retain original provenance, execution outcomes and source reuse status; replaying saved outputs does not constitute fresh inference. Keep actual replay metrics in a separately labeled, dated report.

## Report separately

- **Geometry:** execution errors, successful detector runs, no-candidate abstentions, corner error with annotation uncertainty, and retained frame coverage. Do not score an execution error as geometric abstention.
- **Recognition:** known-label and known-occupancy coverage; correct occupied-piece types/colors; empty-square errors; raw correctness; accepted coverage; accepted wrong labels; and unknown predictions. Score both arms on the same independently known labels. Preserve A's abstentions in end-to-end coverage instead of reporting only frames where A succeeded.
- **Paired effect:** A/B differences on common evaluable frames, plus B performance on A-abstained frames and all exclusions. Improvement in B indicates a geometry contribution. Poor B still leaves classification, crop/preprocessing and unresolved orientation as possible causes. One correlated source cannot establish generalization.
- **Scores:** report fixed score bins and observed error counts with their sample sizes. Softmax values and the existing .95 threshold are uncalibrated scores, not measured probabilities of correctness. Freeze bin edges before results and do not tune thresholds, transformations or model selection on this held-out set; subsequent tuning consumes it as development data.
- **Scope:** exact-board accuracy is available only for independently known 64-square truth. Partial labels must never become an invented complete FEN. Side to move, rights and clocks are unnecessary for this geometry experiment and remain unknown; legal-state tracking and speech need their own explicitly reviewed initial state and sequential test.

## Recorded-evidence replay completed — November 11, 2026

**The new held-out experiment did not run.** The completed comparison replays the five previously evaluated Pexels 6599638 frames. It runs no detector or classifier and sets `heldOut:false`, `freshInferenceRan:false`, `guidanceAllowed:false`, `fen:null`. A separate development runtime check did rerun the existing ONNX classifier on the reused t00 frame; its 64 labels and scores matched exactly. This is not a fresh held-out A/B result.

Run the recorded replay (output must not already exist):

```sh
python3 -B scripts/recognition/replay_geometry_comparison.py \
  --evidence-root /Users/alexmunzon/Library/Developer/ChessCompanionEvaluation \
  --output /tmp/chess-paired-replay.json
```

The replay verifies manifest/frame/video/model hashes, the original classifier/preprocessing and generator code hashes, and each calibration's identity/status/corners against its recorded geometry run. Orientation is the preexisting printed-coordinate permutation `[1,2,3,0]`, not a prediction-selected rotation. Manual outputs still lack per-prediction corner hashes; that historical limitation is recorded. The hypothetical automatic classifier stage uses the same model/policy, but **zero automatic frames actually reached it**.

| Measure | Automatic geometry arm | Annotated-corner control |
| --- | --- | --- |
| Geometry / classifier coverage | 0/5 detected; 0 classifier runs | 5/5 classifier outputs with supplied corners |
| Raw occupied-piece type/color correctness | Not available: inference did not run | 7/74 (9.46%) |
| Accepted correct occupied-type labels / all known occupied types | 0/74 | 0/74 |
| Wrong accepted labels on known occupied types | No accepted output; rate undefined | 15/15 (100%) |
| All accepted predictions | 0/320 | 207/320 |
| Known-label accepted error | No accepted output; rate undefined | 15/189 (7.94%), diluted by correct empty cells |
| Accepted predictions on unknown occupancy | 0/33 | 16/33; correctness unknown |
| Exact-board accuracy | Unscorable | Unscorable: zero fully labeled frames |

Both arms retain all 262 known piece/empty labels, 74 known occupied types and 287 known occupancy labels. Detector abstention is not fabricated empty-square correctness and is not scored as an executed classifier failure.

### Separate error analysis

- **Localization:** the recorded detector abstained on all five frames. Its prediction-conditional classifier accuracy is null. The new native Vision runtime failure is a separate not-run blocker, not a sixth detection failure.
- **Orientation:** canonical mapping is fixed from visible printed board coordinates. No post-hoc rotation or color-based correction is used. This checks the evaluator's coordinate contract; it does not prove the model's internal orientation assumptions.
- **Crop/preprocessing:** the cstr code hash matches the recorded freeze and the runtime check reproduced outputs. Existing crop/tensor tests pass. Neither fact establishes equivalence to upstream training preprocessing or model correctness. There was no crop/threshold/model tuning.
- **Piece class/color:** among 74 known occupied types, raw outputs had 7 correct, 34 wrong type only, 4 wrong color only, 7 wrong type and color, and 22 false-empty predictions. Supplying corners did not solve the problem; crop/preprocessing and classifier assumptions remain candidates.
- **Scores:** all 15 predictions in the ≥.95 score bin on known occupied types were wrong, with mean score 0.9727. They were all “empty.” Across 99 known occupied cells (including unknown piece types), 17 accepted outputs were false empty and zero accepted outputs correctly asserted occupied. These are descriptive results on one reused source, not calibrated probabilities or a threshold-selection study.
- **Occlusion/unknown truth:** 16/33 unknown-occupancy cells received accepted outputs. This measures unsupported certainty, not an observed error rate. Ambiguous piece identities and occluded occupancy are retained as unknown.
- **Temporal inconsistency:** over four adjacent sampled pairs, 14/187 comparisons on known unchanged labels changed raw prediction; 0/130 comparisons where both predictions were accepted changed label. Correctness and stability are separate: persistent wrong “empty” predictions can look stable. Four-second gaps, 69 unknown pairwise cells and zero known labeled changes preclude conclusions about actual intervening moves or legal tracking.

### Improvements and remaining prerequisites

The implemented improvement is a stricter evaluator, not demonstrated recognition accuracy: it rejects mixed model/threshold/source identities, invalid or nonfinite coordinates/scores, contradictory labels, missing detected-arm predictions, stale geometry provenance, and runtime-error-as-abstention substitutions. It keeps inference-conditional accuracy separate from accepted-correct yield and cannot claim a held-out result. Focused metric and artifact-boundary regressions cover these cases. Product recognition remains review-only and legal history gates are unchanged.

A genuine next run needs a **new source-disjoint recording/scene** with all four playing-surface corners visible, visible canonical orientation, varied nonstarting placements, and independently labeled visible piece/color/occupancy cells with uncertainty reasons. Include motion/hand/partial-board segments as a separate abstention challenge. Freeze a second untouched source split before tuning. Document training exclusion where verifiable (for example, a provenance-supported new capture after the frozen model's release); otherwise explicitly report unknown training overlap. No game-history fields are needed for geometry scoring; later legal tracking requires separately reviewed initial state.

The automatic arm additionally needs the original detector to execute successfully in an authorized environment. Its previous Vision error was neither retried nor bypassed. Paired-phone details do not block this offline evaluator and remain unknown; real Gen 1 capture, audio coexistence, audibility and device permissions are separate later gates.

## Verification of the safety boundary

Current permitted checks: 74/74 Node tests and 35/35 Python tests, including 18 new metric/artifact-boundary cases. Existing app-handler, observation and live-session tests retain explicit complete position review, legal successor/stability gates and stale-speech cancellation. A direct boundary check using the actual saved erroneous t00 cstr proposal left all historical fields unknown, rejected incomplete FEN and direct live ingestion, and produced zero engine calls and zero speech messages. The live review flag remains a caller responsibility, not evidence that a person actually reviewed raw predictions. No automatic vision-to-advice adapter was added.

HTTP tests and Vision were not retried; real glasses, camera, browser recognition and audio remain unvalidated. Verification logs, the final replay JSON and input/output hashes are in the session's `outputs/geometry-comparison-2026-11-11/` directory.
