# Real physical chess video: independent diagnostic labels

## Prepared evidence, not an accuracy result

Five actual frames have been downloaded, decoded and independently inspected from [Tima Miroshnichenko's overhead chess video on Pexels](https://www.pexels.com/video/top-view-footage-of-people-playing-chess-6599638/). The annotator did not run the recognition model or inspect its predictions. Recognition evaluation remains a separate step.

The 19.92-second, 25-fps MP4 shows people moving real pieces. Its [Pexels License](https://www.pexels.com/license/) permits free download, use and modification with restrictions. This is a stock-media license, not CC0. The original page links the downloadable 2560×1440 variant recorded in `scripts/recognition/video-manifest.json`. No media or derivative images are included in delivered code. Source SHA256: `1336c9ae9ab1f1d996e628e4c67f578b855ff19127716c0b1d868b0749d49b33`.

Local evidence root: `/Users/alexmunzon/Library/Developer/ChessCompanionEvaluation`. Media and frames are under `video/`; all five frame SHA256 values, timestamps, frame indices, approximate board corners and independently assigned square labels are in the manifest.

## Selection and limitations

Samples at 0, 4, 8, 12 and 16 seconds were selected without model outputs and inspected separately. Frames at 0 and 4 seconds repeat a placement; 12 seconds shows a changed placement. Frames at 8 and 16 seconds contain hands/arms across the board. Thus this is one correlated video, not five independent games or a general accuracy benchmark.

The three unobstructed samples have 64/64 known occupancy labels and 59/64 known piece-type labels each. The two occluded samples have 48/64 and 47/64 known occupancy labels, and 43/64 and 42/64 known piece-type labels. Decorative major-piece silhouettes at c1, d1, e1, e8 and f8 could not be distinguished reliably, so those types remain unknown. Occluded squares remain unknown even when preceding frames suggest their contents. Full FENs and complete-position accuracy must not be fabricated from this set.

Coordinates follow the board's visible printed labels: files a–h run top-to-bottom, ranks 1–8 left-to-right. a1 is the image's top-left board corner; h8 is bottom-right. Dark pieces occupy rank 1 in this staged arrangement. Do not infer orientation from color, silently fix the position, or assume legality. The manifest explicitly provides both image-order corners and canonical a8/h8/h1/a1 corner order. Corner annotations are approximate (8-pixel uncertainty), not automatic detections or user confirmations.

The source does not establish side to move, castling, en passant, repetition history or move number. It does not establish tournament-legal gameplay. No hardware, camera, accounts, deployment, media upload, software installation, model training or threshold tuning was used.

## Reproduction

Download the exact public `mediaUrl` in the manifest to the external evidence directory, verify its hash, and extract each frame using installed ffmpeg:

```sh
ffmpeg -v error -ss 8 -i video/pexels-6599638.mp4 -frames:v 1 video/overhead-8.png
```

The media has time base 1/25 and starts at zero; selected seconds are exact frame boundaries. Installed ffmpeg identified the codec, duration, frame rate and lack of an audio stream. `ffprobe` was unavailable; it was not installed.

For evaluation, freeze/hash the manifest before inference, keep automatic geometry and manual-corner control separate, and report known-label coverage, occupied-square accuracy, empty-square accuracy, abstention and confident wrong answers. Exclude unknown piece types from type accuracy while allowing independently known occupancy scoring. Do not run this partial-label manifest directly through the full-FEN evaluator without explicit adaptation. Preserve model/code hashes in the separate evaluation report.

## Other source considered

Pexels [A Chess Move, by Yaroslav Shuraev](https://www.pexels.com/video/a-chess-move-6184294/) was downloaded and sampled outside the repository. Inspection of its first frame showed shallow focus, overlapping pieces and a cropped board corner, making it inferior for complete labeling. It is not part of this five-frame evaluation manifest. The previously denied Wikimedia original was not retried through another route.

## Current result and next sequential-video gate — November 11

Evaluation has since run: `native/PhotoRecognition/video-results.json` records raw whole-photo recognition at 122/262 known labels correct, 0/74 known occupied types correct, and 120/236 accepted known labels wrong. `native/BoardVision/video-benchmark.json` records 0/5 automatic board detections. These remain historical inference results. This continuation re-scored all ten saved raw/rotation-control predictions against the frozen manifest and reproduced every metric without running inference. The saved evaluator hash differs from the current untracked evaluator; the reason is unknown. Manifest and preprocessing hashes still match. Do not silently relabel the old report with current code hashes.

The five samples are four seconds apart, exceeding the tracker’s default one-second freshness window. Their partial piece labels and unstated history cannot establish a legal initial FEN or validate continuous game tracking. Use this set to diagnose geometry, classification and abstention only.

The next useful recognition step is a separate, frozen recorded sequence with:

1. Independent labels and image orientation, a full board in view, a known piece set, and an explicitly reviewed initial six-field FEN. Record whether earlier repetition history is known; FEN alone is insufficient. If history is unknown, keep guidance blocked.
2. Dense timestamped frames (for example 2–7 fps as an evaluation sampling choice), including unchanged boards, both players’ moves, hands, lifted pieces, motion blur, partial boards and loss/recovery of view. Use capture timestamps and source/session identity, not inference completion time.
3. No ground-truth FEN or labels passed to the recognizer. Score geometry, piece/color and occupancy separately; report exact-board accuracy only where all 64 labels are independently known. Keep manual-corner/orientation controls separate.
4. A replay measuring uncertain/illegal/skipped-move abstention, legal successor recovery, stale engine/speech cancellation, frame age and capture-to-result latency. Human-reviewed label replay is a tracking control, not automatic recognition success.
5. Source-level development/held-out splits and frozen model, preprocessing, threshold and code hashes. The existing diagnostic cannot become a fresh holdout after tuning.

No such complete sequence was created or validated in this continuation. Native capture, actual Gen 1 camera quality and simultaneous glasses audio remain separate hardware gates.

### Experiment to isolate the failure

Before model selection or threshold changes, freeze a new source-disjoint set of real frames with independently labeled pieces and canonical corner order. Verify preprocessing and expected a8–h1 index mapping against upstream references using an asymmetric orientation fixture; no best-fit rotation chosen from predictions. Run the **same** crop/classifier pipeline twice per frame: (A) automatic corners and (B) independent annotated corners. Score geometry before classification, then compare identical known-label/occupied-type/abstention metrics in both arms. An improvement in B isolates a localization contribution; poor B leaves classification, crop/preprocessing or unresolved orientation as candidates. Score the whole-photo model separately since swapping models confounds this comparison. Keep partial labels and occlusions explicit, and do not infer a legal FEN from either arm. This experiment is planned, not yet performed.

The subsequent same-classifier recorded-evidence replay and its stricter scoring are documented in `PAIRED_EVALUATION.md`. It is explicitly development replay, not the proposed new held-out experiment. The raw manual control remains 7/74 occupied types correct; its accepted occupied-type correctness is 0/15.
