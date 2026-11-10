# Chess Practice
User goal: repurpose the private Meta-glasses practice project for chess with strong move analysis, validate as much as possible before glasses arrive, and reuse verified infrastructure.
First milestone: a runnable local board/FEN review UI, legal-move engine plus strong local Stockfish analysis, stale-result guards and tests. Offline board-corner recognition/calibration is separate from piece recognition. Real glasses capture/audio were never implemented in blackjack and cannot be claimed reused.
Historical source ../blackjack-practice commit c828fbec2be4688e15d17a06533b2fdf88cf5b8f contains verified simulator lifecycle controls. c60a2d1 preserves the failed experimental card-recognition baseline. Do not replace or delete either.
No model promises: bounded Stockfish search is strong analysis, not proof of optimality in arbitrary positions. Actual physical board piece recognition, exact glasses/phone compatibility and audio remain unverified.
