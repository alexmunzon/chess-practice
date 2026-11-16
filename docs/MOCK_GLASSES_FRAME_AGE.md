# Mock-glasses frame-age harness (Phase 5 of MOCK_DEVICE_KIT_PLAN.md, 2026-11-16)

**No real latency was measured.** Meta's Mock Device Kit plays a pre-encoded file inside the Simulator with no radio,
so every number below describes the mock and the harness, never real glasses. The live trust decision is unchanged:
every glasses frame is still `.unknownDAT` and can never get a permit. Evidence (outside the repo):
`/Users/alexmunzon/chess-builds/mock-glasses-phase5-2026-11-16/` (`run1..3/`, `run1..3-summary.json`, `mutation-check.txt`).

## Verdict (3 Simulator runs, about 4 minutes each)

None of the three methods rejected 100% of injected stale frames in the mock. Each fails in the way the plan predicted.

| Method (age limit) | Stale frames rejected | Fresh frames wrongly rejected (steady state) | Where stale frames got through |
| --- | --- | --- | --- |
| 1 Nonce (3.0 s, margin 0.05 s) | 159 of 162 | 103 of 3411 (90 of 3038) | 3 frames held 3.10-3.13 s (run 2), age bound 2.94-2.97 s |
| 2 Offset, 10 s window (excess 0.25 s) | 2861 of 3407 | 193 of 7294 (0 of 4483), all warm-up | delay present from stream start 183 of 366; 1.2 s queue longer than window 363 of 1260 |
| 2 Offset, whole-stream minimum | 3224 of 3407 | 193 of 7294 (0 of 4483), all warm-up | delay present from stream start 183 of 366 |
| 3 Budget + liveness (limit 1.0 s, budget 0.5 s placeholder, gap 0.3 s, 2 agreeing frames) | 674 of 2190 | 756 of 7294 (621 of 4483), all waiting for agreement | any delay before the phone receives the frame: 1.2 s queue 1114 of 1260, start delay 276 of 366, 3 s burst 113 of 180 |
| 3 gap watchdog alone (polls, no frame for > 0.3 s) | 459 of 459 polls rejected (0 of 153, 154, 152 accepted) | n/a | doff: frames keep arriving, watchdog never fires (57-59 of 60 polls accepted per run) |

Per run, stale rejected: method 1 54 of 54, 51 of 54, 54 of 54; method 2 (window) 852 of 1033, 1004 of 1186, 1005 of 1188;
method 2 (whole) 973 of 1033, 1125 of 1186, 1126 of 1188; method 3 226 of 729, 231 of 730, 217 of 731.
Runs 2 and 3 added in-order queues of 0.2 s and 0.3 s. Run loads (1-minute average, start -> end): run 1 6.2 -> 8.3,
run 2 6.4 -> 8.8, run 3 8.8 -> 5.6.

## What "stale" means and how it was injected

The harness app (`native/MockGlassesProbe/FrameAgeHarness.swift`, built by `build_frame_age_harness.py`) streams the
pinned test video (15 frame-index codes, 2 s each, file loops every 30 s) at 720x1280, 30 fps. At each SDK frame
callback it records the time, the timestamp (PTS) and the code, then holds some frames in its own code before the three
rules (`FrameAgeRules.swift`) judge them. Ground truth: hold = judge time - callback time. A frame is stale for a method
when it was held and the hold exceeds that method's age limit. Fresh = never held.

- Downstream: the phone's receipt time is the callback time, then the frame waits (a slow pipeline in the app).
- Upstream: the receipt time is stamped on release (a queue in the radio or SDK that the phone cannot see).
- Scenarios: isolated (every 3rd frame held 0.1, 0.2, 0.3, 0.45, 0.55, 0.95, 1.05, 2, 2.9, 3.1, 5 or 10 s, alternating
  modes); in-order queues of 0.2, 0.3, 0.5, 1.2 s; bursts (held 0.2-3 s, released together); drops (no frames 0.2-3 s);
  frames held 16 s across a fold into the next stream; a 1 s queue from the first frame of a new stream; doff, fold
  and power-off. Polls every 100 ms also ask each rule whether the latest frame is still current.

## Findings per method

**Method 1, nonce.** Readback: 11614 of 11614 frames decoded across 3 runs; 11423 equal the slot implied by the PTS.
The mismatches are the mock showing a code up to 0.134 s before its PTS slot starts. Corruption: 1604 of 1604
unmodified control reads correct; every corrupted variant (one block flipped or grey, 1, 2 or 3 bits flipped in both
copies, heavy noise, blank) abstained 2322 of 2322 times per variant with 0 misreads. The 3 stale accepts come from
the modelled display log: the mock has no real display, so the harness models "code N shown at stream start + 2N",
anchored on the first callback (that anchor was 0.08-0.10 s late). Together with the 0.134 s lead, the log said a code
appeared up to about 0.23 s later than the frames show it, more than the 0.05 s margin. A real display log must never
be later than the moment a code becomes visible, or the margin must cover the error (INFERRED: about 0.25 s here; not
re-run). Codes repeat after 30 s, and the rule bounds a repeated code by its first display, so all 3883 fresh frames
after the wrap were rejected (fail closed; scored separately). Method 1 also needs codes that change faster than 2 s:
with a 2 s code, the bound of a fresh frame is already up to 2 s.

**Method 2, offset.** Mock timestamps: start at 0 on every new stream, strictly increasing within a stream, advance
1.0005-1.0015 s per second, no change at doff, stream ends at fold and power-off (inverse action alone did not resume;
the new stream restarted at 0 about 6.1-6.3 s after unfold or power-on). Thresholds held exactly: in-order 0.2 s queue
accepted 288 of 300 (12 rejected as out of order where the queue ended), 0.3 s queue rejected 301 of 301 (lowest excess 0.301 s).
Out-of-order late frames are always rejected. It cannot see a delay present from the first frame of a stream
(183 of 366 accepted; the rest fell in warm-up), and with a 10 s window it forgets the fresh minimum during a long queue.

**Method 3, budget and liveness.** Delays inside the app are caught exactly (0 of 162 stale accepted). Delays before
receipt are invisible: with a placeholder budget, frames 1-3 s old are accepted as long as they keep arriving. Its
stale rejects in isolated tests come mostly from the two-frame rule (an old frame shows a different code), which would
not help on a still board. The gap watchdog worked in the mock: no poll older than 0.3 s was accepted after drops,
fold or power-off. It cannot detect doff, because the mock keeps streaming.

## What the mock cannot show

Real radio or Bluetooth latency, clock drift, the glasses' timestamp meaning (Meta issue #347), a real display's refresh
lag, a real queue's shape, Gen 1 behaviour and the budget value for method 3. The mock's own delivery delay is unknown
and is not part of "hold".

## Run it

```sh
P=/Users/alexmunzon/chess-builds/mock-glasses-2026-11-15; O=/Users/alexmunzon/chess-builds/mock-glasses-phase5-2026-11-16
python3 -B native/MockGlassesProbe/build_frame_age_harness.py --frameworks $P/phase1/frameworks --video $P/phase2/replay-14.mp4 --out $O/build
xcrun simctl install 746F2CEB-102D-4CFC-8D11-A5924705537F $O/build/FrameAgeHarness.app
python3 -B $O/run_watch.py run4 250 local.chesscompanion.mockglasses.frameage FrameAgeHarness -- --frame-age
python3 -B native/MockGlassesProbe/analyze_frame_age.py $O/run4/container/Documents/frame-age-report.json
python3 -B tests/mock_glasses_frame_age.py   # pure rules, no Simulator: 38 of 38 checks
```

Network watch (Phase 4b `run_watch.py`: lsof every 0.2 s, nettop every 1 s, system log for Meta host names, DNS, background
transfers and network-extension flows): 0 sockets, 0 DNS queries, 0 flow records and 0 Meta lines in all 3 runs. No system
dialog in any screenshot. Blind spots: a connection shorter than the polls, from a process other than the app, mDNSResponder
or nsurlsessiond, is not ruled out.
