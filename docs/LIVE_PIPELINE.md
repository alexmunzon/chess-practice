# Live session adapter core

This is integration infrastructure, not live glasses recognition. No camera, microphone, phone or glasses was connected. `node scripts/replay-live-session.js` uses synthetic reviewed square labels, real local Stockfish and a text-only speech sink. It does not evaluate vision or hardware latency.

Create `LiveSession({engine, speech, color, trackerOptions})`. Engine follows `core/engine.js` analyze signature. Connect a source, explicitly confirm every initial FEN field including historical rights, feed separately human-reviewed labeled frames through `ingestReviewed(frame,{humanReviewed:true})`, and call `guide()` after ingest. Raw image recognizer review drafts are not accepted as trusted recognition. The boolean is an explicit caller responsibility, not evidence of automated classifier validation. No autonomous vision ingestion API exists yet.

The tracker enforces stable, fresh, unique zero/one legal-ply observations. The coordinator gates on side to move and terminal positions, deduplicates speech and checks source, epoch, revision, FEN and engine request identity. Position changes and uncertainty abort pending work. A watchdog checks missing observations. Call `stop()` when leaving the session; create a new session to restart after stop.

Speech adapter contract: `speak(text,{signal,isCurrent,identity})` must check signal and isCurrent immediately before actual playback and abort queued/current playback when signaled. `cancel()` must synchronously cancel queued/current output. A phone implementation must implement these guarantees; an arbitrary adapter ignoring cancellation cannot be made safe by this module. Bounded engine recommendations are not guaranteed optimal. Repetition history is incomplete.

`speak()` may resolve after queueing audio or after playback finishes. The coordinator retains the output identity and abort controller in either case, so changed/uncertain observations, observation timeout, reconnection and stop still cancel playback after the promise resolves. A rejected speech call cancels partial output and permits another `guide()` attempt while the position is still current. Late failure from a cancelled speech call cannot cancel a newer output. These behaviors are tested with injected text/queue adapters; they do not establish real audio timing or glasses routing.

## Offline recorded-frame queue

`RecordedFrameQueue` in `src/core/recorded-frame-queue.js` provides a bounded byte-input seam for offline processors. It is not wired to `LiveSession`, the browser, an engine, speech or a glasses SDK. No camera or device operations are implemented by it.

Create it with `{processor, clock, maxAgeMs, watchdogMs}`. The processor receives `(bytes, {signal, identity})` and must settle its promise only after its processing resources have stopped. The existing photo recognizer can be supplied as an adapter; the queue itself imports no recognizer and starts no subprocess. Unit tests use injected processors. Separate offline checks below exercise the existing real photo processor.

Call `connect({sourceId, mode, sourceSha256})` with mode `prerecorded` or `synthetic`, and retain its returned epoch. The supplied source hash describes the recorded media or synthetic fixture; recording this descriptor does not prove its provenance. Offer `{sourceId, epoch, sequence, capturedAt, bytes}` with strictly increasing sequence and capture time. `capturedAt` uses the same monotonic clock as the queue, not a wall-clock timestamp or a video's original playback timestamp. A replay driver must explicitly map media time to its replay clock. Frames are copied, capped at 8 MiB, and independently SHA-256 hashed.

There is one active processor and at most one pending frame; a newer pending frame replaces the older one. Every new accepted frame clears the previous proposal. Active processing may finish, but its result cannot publish after a newer frame arrives. Stop, reconnect, invalid input and freshness timeout abort processing. Aborting does not release the active slot: if a processor ignores abort or never settles, new work remains bounded and waits rather than launching overlapping processes. `stop()` clears pending input and the watchdog; a later explicit `connect()` starts a new epoch without bypassing a still-active processor.

`snapshot()`/`tick()` expose only current, fresh proposals and queue status. The watchdog also expires missing/stale frames. A result must identify the exact frame hash and remain `needs-human-review`, with `fen:null` and `guidanceAllowed:false`; results claiming reviewed state are rejected. Returned envelopes always carry the offline source descriptor and frame identity with `reviewed:false`. Snapshots are copies. The processor remains responsible for validating piece labels and its model-specific output; the queue never manufactures a position or transfers confirmation from an earlier frame. Default maximum frame age is one second and is configurable for an explicitly offline rehearsal; this is not measured live latency or evidence of hardware readiness.

Source and frame fields are snapshotted before validation. Reentrant source changes during input getters or result serialization cannot publish old work. An old epoch is ignored before reading its potentially malformed payload. Frame/proposal byte limits, monotonic-clock failures, delayed completion, retained active resources, reconnect and cancellation are covered by regression tests.

## Actual offline processor checks — November 11, 2026

The old Staxringold development photo was submitted to this queue through the existing `recognizePhoto(bytes, {signal})` bridge. With an explicitly offline 15-second maximum age, the review-only proposal arrived after 11,582.52 ms. It retained the pinned model/runner hashes and `numericalValidationPassed:false`; no engine or speech was attached. This checks byte transport, provenance and review gating, not new recognition accuracy.

With the unchanged default 1,000 ms maximum age, the real child process was aborted and settled after 1,097.02 ms. No proposal was published and no new request temp directories remained. The watchdog and process teardown introduce delay; the measurement is not a hard real-time guarantee. Earlier injected-processor tests cover late completion even when cancellation is ignored.

Two completed standalone-process measurements separate startup from inference:

| Stage (ms) | First measured process | Second process, existing caches |
| --- | ---: | ---: |
| End-to-end wall time | 11,582.52 | 11,423.94 |
| Model/runner verification | 140.60 | 115.06 |
| Image preprocessing | 121.03 | 108.88 |
| CoreML compile/load | 1,653.10 | 1,391.13 |
| Prediction 1 | 2,924.46 | 3,093.65 |
| Prediction 2 | 2,914.92 | 3,549.30 |
| Prediction 3 | 3,299.83 | 2,797.89 |

These are not a clean cold-cache benchmark or device measurements. `native/PhotoRecognition/RunModel.swift` deliberately performs three predictions on one loaded model and returns the last output. Later predictions remained above one second. Reusing a loaded worker can remove some startup cost but cannot by itself meet the present deadline. No persistent worker, deadline relaxation, model swap or pinned-runner change was made.

The subsequent separately versioned one-plus-three-pass diagnostic is now complete; see `NUMERICAL_DIAGNOSIS.md`. All four predictions per input were identical, but the synthetic reference gate still failed 33/2,496 logits, and every prediction exceeded one second. An unchanged-executable control matched the diagnostic. No optimized runner was adopted. The runtime/backend parity dependency and independent video accuracy failure remain; removing repetitions alone is insufficient for reliable live advice.

Evidence and reproducible offline probe scripts are in the session output folder `recorded-input-2026-11-11`. There was no new footage, automatic geometry run, camera, phone, SDK or audible output in these checks.
