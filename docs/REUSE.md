# What carried over from blackjack

Original source remains at `../blackjack-practice`. The verified companion baseline is `c828fbec2be4688e15d17a06533b2fdf88cf5b8f`; interrupted experimental vision was preserved in `c60a2d1`. No blackjack files were modified for this chess milestone.

## Adapted code, present and tested

- **Image loading and geometry:** `native/BoardVision/BoardCandidates.swift` adapts Apple ImageIO loading, `VNDetectRectanglesRequest`, CoreImage perspective correction and JSON reporting from blackjack's `native/RecognitionLab/CardRecognizer.swift`. It proposes board corners; it does not recognize chess pieces. New Python calibration supplies checker-pattern screening, orientation and 64-square source mapping.

## Reimplemented safeguards, not direct source copying

- **Confirmed-state lifecycle:** blackjack `PracticeSession.swift` and `PracticePresentation/CompanionModel.swift` established explicit review, issued identities and invalidation on edits/interruption. Chess `src/review-state.js` implements the same pattern for complete FEN, search tokens and browser visibility. Tests prove rejection of stale or foreign results.
- **Replay/transport lifecycle:** blackjack `ReplayTransport.swift` established session identity, sequence/time checks, bounded buffers and stale callback rejection. Chess observation tracking implements a new chess-specific validation/reconciliation seam and synthetic replay tests. These are architectural reuse, not an existing real-glasses transport.
- **Offline evaluation:** the old lab's idea of source provenance, ground-truth geometry, degraded fixtures, negative controls and reporting was carried over. The known flawed card rank matching/pooled accuracy logic was not reused. Chess evidence explicitly separates synthetic scenes, labeled observation simulations and the failed real-photo trial.
- **Local practice UX/testing:** explicit review, privacy-first local execution and regression tests carry over. The chess web app and rules/Stockfish integration are new.

## Preserved for a future native adapter, not integrated

- Blackjack's Apple SwiftPM simulator builder and successfully packaged iOS simulator app are usable reference infrastructure for a later phone shell. They are not part of the runnable chess web prototype and have not been rebuilt or claimed as a chess native app.

## Nothing to transfer in these areas

- Live glasses/phone camera capture, camera permissions flow, Bluetooth pairing, glasses SDK transport, overlay display and spoken audio were not implemented in the old project. They remain work to do after device/SDK compatibility is verified.
- Blackjack rank OCR, card geometry thresholds, counting and blackjack strategy are not chess recognition or chess rules. They remain preserved only in the old project.
