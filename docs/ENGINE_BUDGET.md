# Engine time budget (Worker E, 2026-11-15)

Pinned `stockfish-19-single` WASM (the phone's files), Hash 32, 1 thread, Node worker. Quality is in
nodes/depth; Mac wall-clock is "Mac, loaded machine" only (load 12 to 447). Evidence:
`/Users/alexmunzon/chess-builds/engine-budget-2026-11-15/`.

## What the app does today
- The app requests `movetimeMs: 1000` (`OfflineStudy.swift`, `ReplayGame.swift`); `worker-engine.js`
  runs `go movetime 1000` in a **fresh Worker per analysis** (uci, Hash 32, isready, ucinewgame).
- Phone self-test (`phone-run2`) has milliseconds only, no nodes/depth/nps. Seven analyses: 1574-1986 ms
  for six of them, plus a 3463 ms outlier that was the **second** analysis, not the first. Time beyond
  the 1000 ms search (per-request worker startup): 574-986 ms, median about 707 ms, for the six; 2463 ms
  in the outlier; median of all seven about 762 ms.

## Method
- Positions: `node scripts/engine-budget-report.mjs --out ladder.json --positions 102 --seed 20261115`.
  The engine played 40 seeded self-play games: 2 to 5 random opening plies, then 800 to 2000 nodes
  per move, with 5% random moves. Candidates are positions the engine searched where the eval was
  within 600 cp and showed no mate. The set has 31 opening, 40 middlegame and 31 endgame positions.
  There are also 19 hand-written tactics (mates in 1, 2 and 4, hanging queens and rooks, forks,
  promotion). Each tactic was kept only if an 800k-node MultiPV-2 search agreed and the second move
  was at least 150 cp worse (19/19 kept). Total: 121 positions.
- Determinism: three generations gave the same sha256,
  `1dd0409084b4ca2c0f5967bafa31dab2a5adf28efc03ca81667e0adcb1eb8826` (`determinism.txt`).
- Reference: 800k nodes (median depth 21). Budgets: 5k, 20k, 50k, 100k and 200k nodes. The hash is
  cleared before every search.
- Loss = ref eval of ref move minus a reference-depth eval of the budget's move. The second eval
  uses `go depth <ref depth> nodes 400000 searchmoves <move>` with the reference hash still warm.
  Evals are clamped to +-1000 cp (mate = 1000), and negative losses count as 0.
- Bias: same engine, only 4x the top budget (flatters 200k; not ground truth); searchmoves noise
  (0.8-4% of moves scored above the ref move); the 400k cap can stop that eval short.

## Quality versus budget (121 positions)
| budget (nodes) | same move as ref | mean loss cp | p95 loss | loss>100 | loss>300 | tactics | median depth |
|---|---|---|---|---|---|---|---|
| 5k   | 75.2% | 12.3 | 56 | 3.3% (4) | 0.8% (1) | 19/19 | 10 |
| 20k  | 75.2% | 12.7 | 77 | 2.5% (3) | 0.8% (1) | 19/19 | 13 |
| 50k  | 76.0% | 5.0  | 32 | 0 | 0 | 19/19 | 15 |
| 100k | 81.8% | 3.7  | 25 | 0 | 0 | 19/19 | 15 |
| 200k | 88.4% | 1.7  | 14 | 0 | 0 | 19/19 | 17 |

Middlegames: 7.5% lose >100 cp at 5k-20k, none at 50k+. 0/121 still allows up to ~2.5% (rule of three).
The tactics are too easy to separate budgets. Per-phase tables: `ladder.md`, `ladder.json`.

## First search and startup (`--mode first-search`, 10 fresh workers per variant, load 9 to 13)
| variant | to ready | search 1 / median of 2-5 (100k nodes) |
|---|---|---|
| default | 460 ms | 348 / ~281 ms, per-worker ratio 1.09 |
| + 5k-node warm-up (27 ms) | 468 ms | ratio 1.14 (no improvement) |
| `--no-liftoff` | 813 ms | ratio 2.16 |
| `--liftoff-only` | 398 ms | ratio 1.07, every search about 40% slower |
- Compile is lazy (~18 ms) and Hash 32 setup ~2 ms; time-to-ready is wasm *execution* of engine
  init incl. the embedded NNUE net (it tracks the compiler flags: 398/460/813 ms).
- The first search pays ~10% (~60 ms) for lazy compile + tier-up; a 5k-node warm-up did not remove it.
- The big cost is startup, paid on **every** analysis (fresh worker). iPhone JavaScriptCore tiers
  differently; the phone 3.5 s outlier is **not explained** here (99 MB re-instantiation? unverified).
- Re-time on a quiet machine: `node scripts/engine-budget-report.mjs --mode first-search --reps 10 --out FILE`.

## Proposal (not implemented)
Pre-start the next private worker when review begins: uci, Hash 32, isready, a warm-up search on a
fixed built-in position, then `ucinewgame`; hand it over on confirmation, still one never-reused
worker per analysis. Hand over only after the warm-up's `bestmove` + `readyok`; a stray early
`bestmove` would already be rejected (ENGINE_PROTOCOL), never shown as advice.

## Phone estimate (assumption, not measured)
Phone nps is unknown; assume 175k-525k (0.5x-1.5x this Mac's ~350k at load 12), so today's 1000 ms
is ~175k-525k nodes. Phone time = startup (0.6-1.0 s, ~0 if pre-started) + nodes/nps: 50k 0.1-0.3 s,
100k 0.2-0.6 s, 200k 0.4-1.1 s. Fixed nodes also make advice independent of phone heat/load.
**Recommendation:** `go nodes 100000` plus a pre-started worker: advice ~0.2-0.6 s after confirmation
(~0.8-1.6 s without pre-start), at the cost of ~6 more per 100 moves differing from the 200k choice
and 0 per 100 losing >100 cp in this set. First log `nodes`/`nps` on the phone to replace the guess.
