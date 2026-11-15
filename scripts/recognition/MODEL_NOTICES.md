# Recognition model provenance and notices

Recorded November 11, 2026 from existing local artifacts and the saved public-source audit. Model weights remain outside this repository. These records identify declarations and limitations; they do not establish recognition accuracy or complete redistribution clearance.

## cstr/chess-board-photo-onnx

The [model card at revision `4690fd5418ff7c405a76d1c156077ecd865ac053`](https://huggingface.co/cstr/chess-board-photo-onnx/blob/4690fd5418ff7c405a76d1c156077ecd865ac053/README.md) declares `license: mit`. A separate `LICENSE` at that revision returned HTTP 404 during the saved audit, and no weight-specific copyright line was found. Do not substitute an application-code copyright for a verified weight copyright.

Existing classifier artifact hashes:

| File | SHA-256 |
| --- | --- |
| `board_photo_occupancy.onnx` | `dcafa86708036f1c50d2471bcfef838a3973e63bc6e3eef08dd3adccf6e0067d` |
| `board_photo_pieces.onnx` | `79f7833e4fd802eb10de4d2765bb243ec51c40bb5097989af9ff4db789f2a8af` |

The crop-contract reference is [CrispChess commit `0d01798daf9661076675f8505b4cc6995a6529da`](https://github.com/CrispStrobe/CrispChess/tree/0d01798daf9661076675f8505b4cc6995a6529da). Its [application/code MIT license](https://github.com/CrispStrobe/CrispChess/blob/0d01798daf9661076675f8505b4cc6995a6529da/LICENSE) states **Copyright (c) 2024-2026 CrispStrobe**. That source commit is not cryptographically bound to the pinned model revision by the audited evidence. This notice records the reference used to check the local crop contract; it does not assert that local code was copied from that repository. The linked license is the primary source for the full MIT notice.

The model card declares training sources including chesscog synthetic renders (OSF xf3ka, CC BY 4.0), samryan18/chess-dataset (MIT; attribution listed as © 2019 Samuel Ryan, Mukund Venkateswaran, Kurt Convey, Michael Deng), and Roboflow 100 chess-pieces-mjzgj (CC BY 4.0). These are upstream declarations. Training overlap with project photos/video remains unknown, and upstream accuracy claims are not local test results.

RGB/NCHW normalization, class order and directional crop/index maps were checked against the cited sources. Pixel-level parity with upstream resizing, warp sampling, EXIF and color decoding is not established. The manual adapter's software tests do not establish physical-board recognition accuracy.

## ChessQueries / ChessQ Lite

The existing local release `NOTICE` states:

> Required Notice: Copyright (c) 2026 Joël Seytre.

The fine-tuned model weights are distributed under **PolyForm Noncommercial 1.0.0**. The local `LICENSE` contains those terms; [the license URL](https://polyformproject.org/licenses/noncommercial/1.0.0) is also supplied by that file. This is distinct from the repository's own software license.

The same notice identifies incorporated DINOv2 pretrained encoders: **Copyright (c) Meta Platforms, Inc. and affiliates.** DINOv2 is under **Apache License 2.0**, preserved locally as `LICENSE-DINOv2`, with [upstream source](https://github.com/facebookresearch/dinov2). The notice records fine-tuning for chess recognition, addition of a ChessQueries decoder and export to the documented precision. The DINOv2 license does not replace the fine-tuned release's license.

Source of the cstr audit: the continuation session's `work/completion-build/cstr-contract.json`. Source of ChessQ notices: `/Users/alexmunzon/Library/Developer/ChessCompanionEvaluation/models/chessq-lite/NOTICE`, `LICENSE` and `LICENSE-DINOv2`. This documentation update did not acquire, modify or redistribute model weights or upstream source code.
