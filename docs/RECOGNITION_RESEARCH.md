# Recognition research — November 15, 2026

Web research by a subagent (no downloads, no sign-ups). Licence and accuracy claims are as the
agent read them on the linked pages; the orchestrator has not re-verified them. Items marked
"not verified" must be checked at the source before any data or model is used.

## Recommendation

1. **Path A, first: a board shown on a screen.** Find the screen, flatten it to a square, label
   each square empty / white piece / black piece using colour references taken from the
   human-confirmed start position, and let the existing legal-move tracker decide which move
   explains the change. Needs no outside dataset, so almost no licence risk.
2. **Path B, later: a physical board with the same three-way idea.** Small square classifier
   trained on ChessReD2K crops and chesscog renders, adjusted per piece set from the confirmed
   start frame; corners from a keypoint model trained on ChessReD2K corner labels. ChessReD is
   CC BY-NC-SA: fine privately, blocks commercial distribution.
3. **Path C, fallback: fine-tune a YOLO-style piece detector.** Easier, but Ultralytics states
   models trained with its tools are AGPL-3.0 by default.
4. **Stop investing in whole-image "photo to position" models.** This project's own video test
   (cstr, hand-marked corners) got empty-vs-occupied right on 256/287 squares (89.2%) but piece
   type on 7/74 (9.5%). ChessQ-lite got 0/74 occupied piece types on the same real video.

## Datasets

| Name | Size / labels | Real or synthetic | Licence (as read) |
| --- | --- | --- | --- |
| [ChessReD](https://data.4tu.nl/datasets/99b5c721-280b-450b-b058-b2900b69a90f) | 10,800 phone photos from 100 games; piece square per image | Real, several angles | CC BY-NC-SA 4.0 |
| ChessReD2K (subset, same page) | 2,078 images; piece boxes + 4 corners | Real | CC BY-NC-SA 4.0 |
| [chesscog renders](https://github.com/georg-wolflein/chesscog) | 4,888 images; FEN | Synthetic 3D | CC BY 4.0 |
| [samryan18/chess-dataset](https://github.com/samryan18/chess-dataset) | 500 images; FEN | Appears real, not confirmed | "MIT" label, text not read |
| [Roboflow Chess Pieces](https://public.roboflow.com/object-detection/chess-full) | 292 images; piece boxes; one fixed angle | Real | Not verified (page 403) |
| [Fenit](https://data.mendeley.com/datasets/wpp9xnbcp6) | Size not stated; boxes + corners | Not stated | CC BY 4.0 |
| [Kaggle Chess Positions (mirror)](https://huggingface.co/datasets/smallchess/kaggle-chess-positions) | 100,000 2D diagrams; FEN | Synthetic 2D | Mirror says CC0; artwork said to be Chess.com's, so risky to distribute |
| [ChessRender360](https://gts.ai/dataset-download/chessrender360/) | 10,000 renders | Synthetic | Licence not found |

No first-person (head-mounted) chess dataset was found.

## Existing recognizers

| Project | Approach | Reported accuracy | Licence |
| --- | --- | --- | --- |
| [chesscog](https://github.com/georg-wolflein/chesscog) | Classical corner finding, occupancy CNN, piece CNN | 0.23% per-square error on its own synthetic set ([paper](https://arxiv.org/abs/2104.14963)); on ChessReD it found the board in 34.38% of images ([ChessReD paper](https://arxiv.org/html/2310.04086v3)) | MIT label; weights not stated |
| [cstr ONNX](https://huggingface.co/cstr/chess-board-photo-onnx) (already tried here) | MobileNetV3-Small occupancy + 12-class piece model | 99.6–99.9% on seen piece sets, about 85% on an unseen wooden set | MIT on card; no LICENSE file found |
| [ChessReD baseline](https://github.com/tmasouris/end-to-end-chess-recognition) | ResNeXt-101 on the whole image | 15.26% exact boards on ChessReD test | MIT code; weights not stated |
| [ChessQ-lite](https://huggingface.co/joelseytre/chessq-lite) (already tried here) | ViT-S whole image | 91.62% exact boards on its panel; failed on this project's real video | PolyForm Noncommercial |
| [LiveChess2FEN](https://github.com/davidmallasen/LiveChess2FEN) | Board detection + CNN per square | 95% board detection, 92% pieces ([abstract](https://arxiv.org/abs/2012.06858)) | AGPL-3.0 |
| [CameraChessWeb](https://github.com/Pbatch/CameraChessWeb) | In-browser; accepts only legal moves | None published | AGPL-3.0 |

## On-device notes

- Apple Vision rectangle detection returns corner points and suits a bright screen; it found
  nothing on this project's one real-board photo.
- coremltools converts to 16-bit precision by default, which can differ slightly across hardware;
  32-bit is the most predictable but cannot use the Neural Engine
  ([typed execution](https://apple.github.io/coremltools/docs-guides/source/typed-execution.html)).
  This is consistent with the project's one-logit Core ML gate failure, but is not a proven cause.
- Ultralytics: "All Ultralytics YOLO trained models fall under the AGPL-3.0 License by default"
  ([licence page](https://www.ultralytics.com/license)).

## The move-level shortcut

- Koray and Sümer, CVWW 2016 ([pdf](https://vision.fe.uni-lj.si/cvww2016/proceedings/papers/21.pdf)):
  no neural network; reference colours from the start position; each square labelled empty /
  light piece / dark piece; compared with the previous state using move rules. 162 of 164 moves
  across 3 games with a fixed overhead 720p webcam. Limits: shadows, changing light, and the
  board and camera must not move.
- Main risk: one wrong reading makes every later move look illegal, so abstention and re-review
  are required. This project already requires both.

## First experiments

- **A:** record about 30 moves of a screen board through the glasses, replay offline, count moves
  found and wrong moves accepted. More than one wrong accepted move with no abstention fails it.
  Needs glasses capture, which is not yet approved.
- **B:** run only the cstr occupancy model with hand-marked corners on ChessReD2K test images and
  see whether three-way output is good enough for the tracker, before training anything. Needs a
  dataset download decision (about 29 GB for full ChessReD; non-commercial licence).

## Not verified

Roboflow and Kaggle licences (mirrors only); MIT licence files themselves; Fenit size and whether
real; licences of chesscog and ChessReD weights; any iPhone latency for these models.
