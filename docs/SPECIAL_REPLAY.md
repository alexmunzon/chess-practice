# Special-move game in the iPhone Replay mode (2026-11-15)

The app's Replay mode now offers two bundled games in a "Game" picker:

- **Opening (14 frames)**: the existing 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6 sequence, unchanged.
- **Special moves (26 frames)**: the game from `docs/SPECIAL_GAME_SEQUENCE.md`, one frame per
  position: 1.e4 Nf6 2.e5 d5 3.exd6 (en passant) Bf5 4.dxc7 Nbd7 5.cxd8=Q+ (promotion with capture)
  Rxd8 6.d4 e6 7.Nc3 Be7 8.Be3 O-O 9.Qd2 Nb6 10.O-O-O Nbd5 11.Nxd5 Nxd5 12.Bd3 Bxd3 13.Qxd3. Two
  insertable interruption frames: "Show obstructed frame next" (occlusion) and "Show frame with a
  missing piece next" (h2 pawn gone, no legal move explains it).

The recognizer gives full piece labels, so the promotion is read directly; there is no "which piece"
prompt. Safety rules are the same for both games (see the top of `ReplayGame.swift`): one full review,
then legal tracking; text advice only at reviewed-and-tracked positions; any interruption revokes until
a renewed review; late replies never restore advice. Choosing another game acts like Reset: it revokes
at once, cancels work, stops the engine and clears frame, draft and review.

## Bundling

`prepare_app.py --special-replay-directory <generator out>/pixels` copies `frame-000..025.png` to
`ReplaySpecial/frame-NNN.png`, `frame-026.png` to `ReplaySpecial/occlusion.png` and `frame-027.png` to
`ReplaySpecial/missing-piece.png`. All 28 SHA-256 values are pinned in `prepare_app.py` and again in
`ReplayGame.swift`; the manifest and its `evaluatorTruth` are never bundled. `--self-test` now needs
both replay directories. `StudyResources` accepts each game only as a complete, pin-matching group;
the picker lists only games that are fully bundled.

## Checks

- `ReplayGameChecks.swift` (mocks): 26/26, five new `special-*` cases: all 25 plies (FEN and SAN,
  analysis bound to each tracked FEN), occlusion, missing piece, late engine reply after the
  occlusion revoke, switching game mid-game (plus held engine and tracker replies). The mock tracker
  follows a table, so FEN correctness itself comes from the real tracker (self-test, JS test).
- `tests/special-replay-pins.test.js`: pins agree between Swift and Python; the FEN/SAN lists in
  `SelfTest.swift` and `ReplayGameChecks.swift` equal a chess.js replay (tracker FEN convention); with
  `SPECIAL_GAME_DIR` also equal to the generated pixels and manifest.
- Self-test (`--chess-self-test`) adds 7 `special-*` checks after the opening-game checks, under a
  separate 360 s watchdog, and a report section `specialReplayGame` (per-check pass/fail, recognition
  ms per frame, engine search ms). Review there is the labelled scripted fixture, not human review.

Commands and evidence: `/Users/alexmunzon/chess-builds/special-replay-2026-11-15/` (`mocks/run-all.sh`,
`run-sim-selftest.sh`, build reports, Simulator reports with `uptime`).

## Limits

Synthetic clean images only; scripted review; Simulator runs are not phone runs. Interruption frames
are followed by review of the next frame (the app only steps forward), so plies 21 and 23 are
re-established by review in that pass; the uninterrupted pass tracks all 25 plies.
