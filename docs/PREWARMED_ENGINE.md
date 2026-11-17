# Pre-started engine worker

`src/core/prewarmed-engine.js`: `createPrewarmedAnalyzer({createWorker, clock|now, warmupNodes=5000,
maxIdleMs=60000, prewarmTimeoutMs=10000, handoverTimeoutMs=1000})` -> `{prewarm({signal}), analyze, dispose,
state}`. Wired into the local phone runtime. Tests: `tests/prewarmed-engine.test.js`. Evidence:
`/Users/alexmunzon/chess-builds/prewarmed-engine-2026-11-16/` (round 2 in `round2/`) records the original Node experiments. Later phone evidence is separate; see the current verification record.

## Kept from `createWorkerAnalyzer` (fresh path is a copy; its mock tests are copied)
Confirmation, six-field legal FEN, limits and deadlines checked before any worker; terminal position -> no
move, no worker; start-up and search deadlines by timer AND monotonic clock on every message (a late result
is `TIMEOUT`); duplicate handshakes ignored; legal `bestmove` only; PV shown only if wholly legal, exact,
multipv 1; 1 MB output cap; every exit detaches, `stop`/`quit`, terminates; `WORKER_REUSED`; result carries
the caller's `requestId` and FEN.

## Decisions
- **Limit:** `nodes` 1,000-2,000,000 -> `go nodes N`; wall-clock `searchTimeoutMs` (3000) + `graceMs`
  fails closed. Both limits -> `INVALID_LIMIT`; neither -> `movetimeMs` 1000 (today's default).
- **Extra result fields** (`analysis.nodes`, `nps`, `limit`, `prewarmed`, `startup {path, fallbackReason,
  waitedMs}`): DeviceBackend rebuilds its reply and ignores them; Swift `Adapters.swift` demands an exact
  key set, so forwarding one needs a change on both sides.
- **Spare:** `uci`, Hash 32, `isready`, then a 5k-node warm-up on `WARMUP_FEN`; its `bestmove` is dropped
  unread; then `stop`, `ucinewgame`, and TWO `isready`/`readyok` cycles before "ready". Any other
  `bestmove` (before the warm-up, or in either drain window) discards the spare. Prewarm never rejects;
  any failure -> `false`, and analyze uses a fresh worker.
- **No reuse:** one analysis per worker, then terminate. Attribution is by listener identity, not content.
- **Hand-over:** the analysis attaches its own listeners and drains with `isready` under
  `handoverTimeoutMs` (1000: measured drain 0.2-10 ms at Mac load 112-155). Silence, error or send failure
  -> drop the spare, fresh worker with a NEW full `startupTimeoutMs`. One fallback at most, so start-up is
  bounded by `2 x startupTimeoutMs + handoverTimeoutMs`, reported in `analysis.startup`.
- **Analyze during warm-up waits** up to `startupTimeoutMs`, then (or on spare failure) falls back as above.
- **No second engine:** `prewarm()` returns `false` without creating a worker while any analysis runs.
- **Native busy rule (wired app):** `NativeEngineRuntime.submit` refuses `prewarm` and `cancelPrewarm` while a
  real engine or Replay tracker request is pending ("Runtime busy; prewarm skipped."). Kept for `cancelPrewarm`
  too, because the page's `DeviceBackend.handle` cancels the running job before it reads any command. What a
  refused cancel leaves depends on what is pending. A pending analysis has already taken the spare (or is
  waiting for it), so nothing is left over. A pending Replay tracker or `position`/`move` request has not, so
  a ready spare survives (the app ignores the refusal) until the 60 s idle age or shutdown, or until the next
  analysis takes it: at most about 70 s (10 s start-up plus 60 s idle). It holds no position, and no advice
  comes back: the next analysis still needs a confirmed, reviewed position and searches that position itself.
  Pinned by `RuntimeGuardChecks.swift`.
- **Signals:** repeated `prewarm` calls share one spare; ANY caller's abort discards it (a cancel means some
  part of the app is leaving review; keeping a 99 MB engine for a stale caller is worse than re-creating
  it). The app should still own one prewarm controller.
- **Idle age:** 60 s default (1 s-10 min), timer plus a clock check when taken (iOS may suspend timers or
  reclaim memory).

## What protects against a leaked warm-up result (layers, strongest first)
1. **PV binding (both paths):** a `bestmove` is accepted only if, after THIS analysis' `go`, a legal PV
   (multipv 1, any bound) arrived and `bestmove` equals the first move of the last PV at the deepest depth;
   else `ENGINE_PROTOCOL`. A probe of 242 real searches (121 positions x 1k and 100k nodes) matched on 242;
   the last EXACT PV would have mismatched 8, so bound lines count. Residual: a stray `bestmove` that
   happens to equal the current PV's move is accepted, but then it IS the search's own choice.
2. **Ordering:** a `bestmove` before this analysis' `go` (including during the hand-over drain) is
   `ENGINE_PROTOCOL`.
3. **Drain cycles:** two `isready` round trips after the warm-up; a duplicate landing there discards the
   spare. This only catches duplicates delivered before hand-over; it guarantees nothing about later ones.
4. **Listener identity:** spare listeners are removed at hand-over; old workers' callbacks are dead.
5. **Backstop only:** `WARMUP_FEN` has White pieces only on ranks 3-6, so no warm-up move is legal in the
   start position or after any first White move (enumerated in a test). Other positions are not covered.

## Results
- Round 1 (old warm-up position, load 11.6-72.8): fresh and prewarmed gave the same move and the same node
  count on 121/121 (sha256 of the seeded 102 matches ENGINE_BUDGET); timing 1191 vs 409 ms (0.34).
- Round 2 timing, 10 reps, `nodes 100000`: fresh 1615 ms, prewarmed 590 ms, ratio 0.37, prewarm 945 ms;
  load 112 before, 155 after (overloaded machine; times are rough).
- Round 2 identity was NOT re-run (engine budget used by the probe, timing and tests at load ~150). Re-run:
  `PREWARM_IDENTITY_LADDER=/Users/alexmunzon/chess-builds/engine-budget-2026-11-15/ladder.json node --test
  --test-name-pattern=opt-in tests/prewarmed-engine.test.js` (add `PREWARM_IDENTITY_RECORDED=<round-1
  result-identity.json>` to halve it).

## Integration checklist (implemented; retained as a source map)
1. `runtime.js`: `const engine = createPrewarmedAnalyzer({createWorker})`; `DeviceBackend({analyzer:
   engine.analyze})`; expose `prewarm`/`cancelPrewarm` (one AbortController); `shutdown()` calls `dispose()`.
2. `device-backend.js`: `analyze` takes exactly one of `movetimeMs` (50-3000) or `nodes` (1000-2000000).
3. `scripts/build-device-runtime.mjs`: add `prewarmed-engine`; asset test list and count 15 -> 16.
4. Swift: node budget on `AnalysisRequest`; `LocalChessAdapters.analyze` sends `nodes: 100000`; range guard.
5. Flow: `prewarm` when the review screen opens; cancel on leaving the mode, backgrounding, shutdown.

## Current verification and limits — November 17, 2026

The engine is integrated with the iPhone app. The committed `53a8bfa` build passed 34 of 34 phone self-test checks in two complete runs on November 17 (scripted review, synthetic pictures). Engine searches in those runs were typically 0.16–0.17 seconds; this is a bounded observed sample, not a timing guarantee. Evidence: `chess-builds/phone-selftest-2026-11-17/` outside the repository; [verification record](VERIFICATION.md).

In-flow Simulator instrumentation subsequently found intermittent engine freezes: 18 of 21 misses searched at normal speed, then went silent; three never answered the first command. The earlier “35x slower” description and attribution to machine load are superseded. The cause remains unresolved, and investigation is parked. The broader recorded phone sample had zero misses in 470 searches; that is not proof against all phone failures. Evidence: `chess-builds/slow-search-experiment-2026-11-17/FINDINGS.md`.

Specific behavior when iOS suspends or kills an idle spare is not comprehensively device-tested. Idle checks and fallback logic are protections, not a substitute for that test. Original Node comparison runs above retain their original scope; do not treat them as phone results or repeat them on held-out data to tune the engine.
