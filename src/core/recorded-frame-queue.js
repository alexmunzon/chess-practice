import { createHash } from 'node:crypto';

export const MAX_RECORDED_FRAME_BYTES = 8 * 1024 * 1024;
const MAX_PROPOSAL_BYTES = 256 * 1024;
const typedArrayByteLength = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(Uint8Array.prototype), 'byteLength').get;
const typedArraySet = Uint8Array.prototype.set;
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const identity = value => typeof value === 'string' && /^[\w.:/-]{1,128}$/.test(value);
const time = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const unreviewed = value => ['humanReviewed', 'humanConfirmed', 'reviewed', 'confirmed', 'confirmation']
  .every(key => !Object.hasOwn(value, key) || value[key] === false);

function sourceDescriptor(source) {
  if (!record(source)) throw new Error('An offline source descriptor is required.');
  const {sourceId, mode, sourceSha256} = source;
  if (!identity(sourceId) || !['prerecorded', 'synthetic'].includes(mode) || !hash(sourceSha256)) {
    throw new Error('An offline sourceId, prerecorded/synthetic mode and sourceSha256 are required.');
  }
  return Object.freeze({sourceId, mode, sourceSha256});
}

function reviewProposal(result, frameSha256) {
  if (!record(result) || result.status !== 'needs-human-review' || result.fen !== null ||
      result.guidanceAllowed !== false || result.sourceSha256 !== frameSha256 || !unreviewed(result)) {
    throw new Error('The processor must return an unconfirmed review-only proposal for these frame bytes.');
  }
  const serialized = JSON.stringify(result);
  if (typeof serialized !== 'string' || Buffer.byteLength(serialized) > MAX_PROPOSAL_BYTES) throw new Error('Review proposal exceeded its size limit.');
  const clone = JSON.parse(serialized);
  // Validate the serialized boundary too; a custom toJSON must not change trust flags.
  if (!record(clone) || clone.status !== 'needs-human-review' || clone.fen !== null ||
      clone.guidanceAllowed !== false || clone.sourceSha256 !== frameSha256 || !unreviewed(clone)) {
    throw new Error('Invalid serialized review proposal.');
  }
  return clone;
}

/** Offline byte transport only. It never confirms state or invokes engine/speech.
 * A processor must settle only after its processing resources have stopped.
 * Abort does not free the active slot until that promise actually settles. */
export class RecordedFrameQueue {
  #processor; #clock; #maxAgeMs; #watchdogMs; #timer = null;
  #source = null; #epoch = 0; #sequence = -1; #capturedAt = -1; #lastNow = -1;
  #active = null; #pending = null; #proposal = null; #reason = 'not-connected';
  lastError = null;

  constructor({processor, clock = () => performance.now(), maxAgeMs = 1000, watchdogMs = 50} = {}) {
    if (typeof processor !== 'function' || typeof clock !== 'function' ||
        !Number.isInteger(maxAgeMs) || maxAgeMs < 1 || maxAgeMs > 120_000 ||
        !Number.isInteger(watchdogMs) || watchdogMs < 1 || watchdogMs > 1000) throw new Error('Invalid recorded frame queue options.');
    this.#processor = processor; this.#clock = clock; this.#maxAgeMs = maxAgeMs; this.#watchdogMs = watchdogMs;
  }

  #invalidate(reason) {
    this.#proposal = null; this.#pending = null; this.#reason = reason;
    this.#active?.controller.abort();
  }

  #now() {
    let now;
    try { now = this.#clock(); }
    catch {
      this.#invalidate('invalid-clock');
      throw new Error('Recorded frame clock failed.');
    }
    if (!time(now) || now < this.#lastNow) { this.#invalidate('invalid-clock'); throw new Error('Recorded frames require a monotonic clock.'); }
    this.#lastNow = now; return now;
  }

  #fresh(frame, now) { return frame.identity.capturedAt <= now && now - frame.identity.capturedAt <= this.#maxAgeMs; }

  #current(job, now) {
    return !job.controller.signal.aborted && this.#source !== null &&
      job.frame.identity.epoch === this.#epoch && job.frame.identity.sequence === this.#sequence && this.#fresh(job.frame, now);
  }

  #expire(now) {
    if (this.#proposal && now - this.#proposal.identity.capturedAt > this.#maxAgeMs) {
      this.#proposal = null; this.#reason = 'frame-timeout';
    }
    if (this.#pending && !this.#fresh(this.#pending, now)) { this.#pending = null; this.#reason = 'frame-timeout'; }
    if (this.#active && !this.#fresh(this.#active.frame, now)) {
      this.#active.controller.abort(); this.#reason = 'frame-timeout';
    }
  }

  #view() {
    return structuredClone({
      source:this.#source, epoch:this.#epoch, latestSequence:this.#sequence,
      status:!this.#source ? 'disconnected' : this.#proposal ? 'needs-human-review' :
        this.#active?.controller.signal.aborted ? 'waiting-for-processor' : this.#active ? 'processing' : 'waiting-for-frame',
      reason:this.#reason, guidanceAllowed:false, reviewed:false, fen:null,
      active:this.#active ? {epoch:this.#active.frame.identity.epoch, sequence:this.#active.frame.identity.sequence, aborted:this.#active.controller.signal.aborted} : null,
      pending:this.#pending ? this.#pending.identity : null,
      bufferedBytes:(this.#active?.frame.bytes.length ?? 0) + (this.#pending?.bytes.length ?? 0),
      proposal:this.#proposal, lastError:this.lastError,
    });
  }

  connect(source) {
    const epoch = this.#epoch;
    const descriptor = sourceDescriptor(source); this.#now();
    if (this.#epoch !== epoch) throw new Error('Source connection changed while reading its descriptor.');
    // Change identity before abort listeners can synchronously deliver old frames.
    this.#source = descriptor; this.#epoch++;
    this.#sequence = -1; this.#capturedAt = -1; this.lastError = null;
    this.#invalidate('source-connected');
    if (!this.#timer) {
      this.#timer = setInterval(() => { try { this.tick(); } catch (error) { this.lastError = error instanceof Error ? error.message : 'Recorded queue watchdog failed.'; } }, this.#watchdogMs);
      this.#timer.unref?.();
    }
    return this.#view();
  }

  stop() {
    this.#source = null; this.#epoch++; this.#invalidate('stopped');
    clearInterval(this.#timer); this.#timer = null; return this.#view();
  }

  tick() { this.#expire(this.#now()); return this.#view(); }
  snapshot() { return this.tick(); }

  offer(input) {
    const source = this.#source, epoch = this.#epoch;
    const changedSource = () => this.#source !== source || this.#epoch !== epoch;
    const superseded = () => ({...this.#view(), accepted:false, ignored:'stale-session'});
    try {
      // Read identity once before other getters, so malformed old callbacks
      // can be ignored without inspecting their remaining payload.
      const incomingEpoch = record(input) ? input.epoch : undefined;
      if (changedSource()) return superseded();
      if (Number.isSafeInteger(incomingEpoch) && incomingEpoch >= 1 && incomingEpoch !== epoch) {
        return {...this.snapshot(), accepted:false, ignored:'stale-session'};
      }
      if (!source) return {...this.#view(), accepted:false, ignored:'not-connected'};
      const fields = ['sourceId', 'epoch', 'sequence', 'capturedAt', 'bytes'];
      if (!record(input) || Object.keys(input).length !== fields.length || fields.some(key => !Object.hasOwn(input, key))) {
        throw new Error('Invalid recorded frame fields.');
      }
      const {sourceId, sequence, capturedAt, bytes:inputBytes} = input;
      if (changedSource()) return superseded();
      const now = this.#now(); this.#expire(now);
      if (changedSource()) return superseded();
      const byteLength = inputBytes instanceof Uint8Array ? typedArrayByteLength.call(inputBytes) : 0;
      if (sourceId !== source.sourceId || incomingEpoch !== epoch ||
          !Number.isSafeInteger(sequence) || sequence < 0 || !time(capturedAt) ||
          byteLength === 0 || byteLength > MAX_RECORDED_FRAME_BYTES) {
        throw new Error('Invalid frame identity, timestamp or bytes (maximum 8 MiB).');
      }
      if (sequence <= this.#sequence || capturedAt <= this.#capturedAt) {
        return {...this.#view(), accepted:false, ignored:'repeated-or-reordered-frame'};
      }
      if (capturedAt > now || now - capturedAt > this.#maxAgeMs) throw new Error('Frame is stale or from the future.');
      // Native typed-array access/copy uses internal slots, not overridable
      // byteLength/length getters or iterators on the supplied byte view.
      const bytes = Buffer.allocUnsafe(byteLength);
      typedArraySet.call(bytes, inputBytes);
      if (typedArrayByteLength.call(bytes) !== byteLength || bytes.length > MAX_RECORDED_FRAME_BYTES) throw new Error('Invalid copied frame length.');
      const frameIdentity = Object.freeze({...source, epoch, sequence,
        capturedAt, frameSha256:createHash('sha256').update(bytes).digest('hex')});
      if (changedSource()) return superseded();
      if (sequence <= this.#sequence || capturedAt <= this.#capturedAt) {
        return {...this.#view(), accepted:false, ignored:'repeated-or-reordered-frame'};
      }
      this.#sequence = sequence; this.#capturedAt = capturedAt;
      this.#proposal = null; this.lastError = null; this.#reason = 'unreviewed-frame';
      this.#pending = {bytes, identity:frameIdentity};
      this.#drain();
      return {...this.#view(), accepted:true};
    } catch (error) {
      if (changedSource()) return superseded();
      this.#invalidate('invalid-frame'); this.lastError = error instanceof Error ? error.message : 'Invalid recorded frame.';
      return {...this.#view(), accepted:false};
    }
  }

  #drain() {
    if (this.#active || !this.#pending || !this.#source) return;
    try {
      const now = this.#now(); this.#expire(now);
      if (!this.#pending) return;
      if (this.#pending.identity.epoch !== this.#epoch || this.#pending.identity.sequence !== this.#sequence) {
        this.#pending = null; return;
      }
      const job = {frame:this.#pending, controller:new AbortController()};
      this.#pending = null; this.#active = job;
      void this.#process(job);
    } catch (error) { this.lastError = error instanceof Error ? error.message : 'Recorded queue failed.'; }
  }

  async #process(job) {
    try {
      const result = await this.#processor(job.frame.bytes, {signal:job.controller.signal, identity:job.frame.identity});
      const now = this.#now(); this.#expire(now);
      if (!this.#current(job, now)) return;
      const proposal = reviewProposal(result, job.frame.identity.frameSha256);
      // Result getters/toJSON can call back into the queue; serialization must
      // not let an old job publish after a reconnect, stop or elapsed deadline.
      const publicationTime = this.#now(); this.#expire(publicationTime);
      if (!this.#current(job, publicationTime)) return;
      this.#proposal = {identity:job.frame.identity, result:proposal, reviewed:false, guidanceAllowed:false, fen:null};
      this.#reason = 'review-only-proposal';
    } catch (error) {
      if (!job.controller.signal.aborted && job.frame.identity.epoch === this.#epoch && job.frame.identity.sequence === this.#sequence) {
        this.#proposal = null; this.#reason = 'processor-error';
        this.lastError = error instanceof Error ? error.message : 'Recorded frame processing failed.';
      }
    } finally {
      if (this.#active === job) { this.#active = null; this.#drain(); }
    }
  }
}
