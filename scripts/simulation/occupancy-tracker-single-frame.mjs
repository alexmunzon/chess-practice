// SIMULATION ONLY. Emulates a single-picture agreement rule (agreeFrames 1) for comparison rows, WITHOUT any route in
// src/core/occupancy-tracker.js that accepts agreeFrames below 2. Each counted picture is fed to a normal tracker
// (agreeFrames 2, minFrameGapMs 0, minSettleMs 0, castlingRookSettleMs 0, readyDwellMs 0) twice: as itself and as a twin 1 ms later with a different hash and the
// next sequence number (the inner tracker gets its own consecutive numbering, round 6). Not bundled, never used by the app.
// Requires the caller's pictures to be > 1 ms apart, in order and without gaps, and the caller's hashes not to start with "f".
import { OccupancyTracker } from '../../src/core/occupancy-tracker.js';

export class SingleFrameSimulationTracker {
  #inner; #lastAt = 0; #seq = 0; #outer = null;
  constructor(options) { this.#inner = new OccupancyTracker({ ...options, agreeFrames: 2, minFrameGapMs: 0, minSettleMs: 0, castlingRookSettleMs: 0, readyDwellMs: 0 }); }
  get options() { return { ...this.#inner.options, agreeFrames: 1, emulation: 'each picture counted twice (simulation only)' }; }
  confirm(input) { return this.#inner.confirm(input); }
  invalidate(reason) { return this.#inner.invalidate(reason); }
  tick(atMs) { return this.#inner.tick(atMs); }
  snapshot() { return this.#inner.snapshot(); }
  // The twin picture is stamped 1 ms after the real one, so an answer stamped at the real time is moved to the twin's time.
  answerPromotion(input) { return this.#inner.answerPromotion({ ...input, atMs: Math.max(input.atMs, this.#lastAt) }); }
  ingest(picture) {
    const remap = (sequence, frameSha256, capturedAtMs) => ({ ...picture, identity: { ...picture.identity, sequence, frameSha256 }, capturedAtMs });
    // A gap or reorder in the caller's numbering is passed on as one (the inner numbering skips too), so the inner tracker sees it.
    const key = `${picture.identity.sessionId}:${picture.identity.epoch}`, outer = picture.identity.sequence;
    if (this.#outer?.key === key) this.#seq += outer > this.#outer.seq ? outer - this.#outer.seq : -1_000_000_000;
    else this.#seq += 1_000_000_000; // a new session: inner numbering jumps (the inner tracker resets its sequence check on confirm)
    this.#outer = { key, seq: outer };
    const first = this.#inner.ingest(remap(this.#seq, picture.identity.frameSha256, picture.capturedAtMs));
    this.#lastAt = Math.max(this.#lastAt, picture.capturedAtMs);
    if (first.event !== 'agreement-pending') return first;
    this.#lastAt = picture.capturedAtMs + 1;
    this.#seq++; // the twin takes the next inner number; the caller's next picture continues after it
    return this.#inner.ingest(remap(this.#seq, 'f' + picture.identity.frameSha256.slice(1), picture.capturedAtMs + 1));
  }
}
