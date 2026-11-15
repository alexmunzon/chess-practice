# Recognizer performance: 2026-11-15

**Bottom line.** The phone build is compiled **without optimization**. `prepare_app.py` calls `swiftc` with no `-O`, so Swift falls back to its default `-Onone` debug code. The Mac's earlier figure of about 40 ms came from the README build, which does use `-O`. On this Mac the same code takes about **3,000–3,900 ms per frame at -Onone** and **41 ms at -O**, roughly 75–95× apart. That gap explains the 40× phone-vs-Mac difference. Reloading the template on every call costs only about 3 ms at -O and about 13 ms at -Onone. After the patches the Mac takes about 27 ms per frame, and all 4,992 square decisions are byte-identical.

## Setup
- Mac: Apple M1, Swift 6.2.4, the app's flags (`-parse-as-library -swift-version 6`). The machine was shared with other jobs (load average 7–59), so CPU time is reported next to wall time, and before/after variants ran interleaved in the same window.
- Inputs: the frozen corpus (78 PNGs, 768×768) and the replay sequence (15 PNGs).
- Harness: `work/bench/Bench.swift`.
- `cli` mode is the NativeVisionCLI path.
- `app` mode copies what `OfflinePixelRecognizer` does on every call: re-read the manifest, read and SHA-256-check the template, parse and prepare it, and hash the image twice more.
- `appcached` mode is the patched adapter.
- Measured: the earlier device build reports contain no `-O` (`replay-mode-2026-11-15/device-normal`, `selftest-2026-11-15/device`).

## Current code, time per stage (mean ms per call, 78 frames, instrumented copy; same decisions)
| Stage | CLI -Onone | App -Onone | CLI -O | App -O |
|---|---|---|---|---|
| PNG decode | 192 (4%) | 140 (5%) | 9.5 (19%) | 11.7 (14%) |
| Marker/board location | 130 (3%) | 92 (3%) | 1.5 (3%) | 2.0 (2%) |
| Rectification | 537 (12%) | 371 (12%) | 9.8 (19%) | 18.0 (22%) |
| Tile copy + background | 218 (5%) | 134 (4%) | 5.6 (11%) | 9.0 (11%) |
| Photometric correction | 232 (5%) | 144 (5%) | 3.2 (6%) | 5.1 (6%) |
| **Feature extraction** | **2,696 (60%)** | **1,787 (59%)** | **17.3 (34%)** | **27.9 (34%)** |
| Template matching | 398 (9%) | 261 (9%) | 2.3 (5%) | 2.9 (4%) |
| Edge/border/decision | 95 (2%) | 65 (2%) | 1.7 (3%) | 2.8 (3%) |
| Template load/prepare per call | n/a | 13.5 | n/a | about 3 |
| Result assembly + SHA-256 | 0.2 | 0.2 | 0.3 | 0.5 |

Columns were measured at different load levels, so compare percentages within a column, not totals across columns.

## Why the phone is slow
1. **Measured:** no optimization flag. Same Mac, same code: about 3,000 ms at -Onone vs 41 ms at -O, roughly 75×.
2. **Measured:** reloading the template per call adds only about 3 ms (-O) or 13 ms (-Onone).
3. **Hypothesis:** main-actor work is not the bottleneck. Recognition runs on its own actor; only the frame read and one hash run on the main actor.
4. **Hypothesis:** the phone (1.5–1.8 s) beats this Mac at -Onone (about 3 s) because it has faster cores and was not loaded.

## Changes
- `recognizer-perf.patch` (ChessCompanionVision):
- Template matching keeps 13 running sums advancing together, each in the same order as before.
- Blur and resize reuse buffers; the resize weights are computed once.
- Marker search uses a flood fill instead of a `Set`.
- Rectification, tile copy, correction and border loops use buffer pointers with the same expressions.
- Marker target colors are computed once.
- `NativeSyntheticRecognizer` is declared `Sendable`.
- No threshold, template or tolerance change, and floating-point additions keep their order.
- `app-side.patch`:
- The actor prepares the recognizer once and keeps it; a failed preparation is not cached.
- The image is hashed once per call instead of twice.
- `prepare_app.py` adds `-O`. A full iOS app compile took 30 s (15 s at -Onone), under the 180 s timeout.

## Before/after (ms per call, interleaved, two repeats)
| Path | Wall median | Wall p95 | CPU median | CPU p95 |
|---|---|---|---|---|
| CLI current -O | 40.7–41.3 | 50.7–59.9 | 40.5–41.0 | 46.9–50.1 |
| CLI optimized -O | 27.3–28.1 | 33.0–33.9 | 27.2–27.8 | 31.2–32.2 |
| App current -O | 44.1–45.5 | 57.5–88.8 | 43.5–44.3 | 50.8–58.6 |
| App cached + current vision -O | 41.0–42.8 | 57.0–85.0 | 40.8–42.1 | 48.7–59.5 |
| **App patched -O** | **26.6–27.1** | **29.0–30.7** | **26.4–27.0** | **28.6–29.7** |

Replay sequence, 15 frames, wall median / p95 at -Onone:
| Path | -Onone |
|---|---|
| CLI current | 3,065 / 3,149 |
| App current (ships today) | 3,049 / 3,374 |
| CLI optimized | 2,314 / 2,546 |
| App patched | 2,301 / 3,237 |

At -O on the same 15 frames, the patched app path ran 25.6 / 26.9.

## Identity proof (identity-report.jsonl)
Every comparison found 0 differences: whole results byte for byte, plus per-square labels, confidence, abstention reasons and metric bit patterns.
- Corpus: 78/78 frames, 4,992/4,992 squares, for CLI current vs optimized at both flags, current -O vs -Onone, and app current vs patched.
- Replay sequence: 15/15 frames, 960/960 squares.

## Thread safety
- The cache is actor-isolated, so calls are serialized and need no lock.
- The library has no mutable globals; the resize weights are an immutable `static let`.
- Swift 6 typechecks with warnings as errors pass for:
- All app sources on iOS 17.2 (arm64) and on macOS 14.
- The vision library on macOS 13 and iOS 16.

## Patch checks
- Made against the working tree at a13ed1c.
- `git apply --check` passes for each patch and for both together.
- Applying them reproduces the tested sources exactly.
- The repo is unmodified.

## Not verified
- Phone timing, until the patched app runs on the iPhone 17.
- The whole-app `-O` change: rerun the self-test on the Simulator and the phone.
- Possible later step: run rectification and tiles in parallel across cores.
