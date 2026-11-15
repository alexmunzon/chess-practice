import { ObservationTracker } from './observation.js';
import { loadPosition, positionPayload } from './position.js';

import { spokenMove } from './move-speech.js';
export { spokenMove } from './move-speech.js';

/** Phone adapters must honor signal and isCurrent immediately before playback,
 * and stop all queued/current playback synchronously in cancel(). */
export class TextSpeechSink {
  messages = [];
  cancel() {}
  async speak(text, {signal, isCurrent}) {
    if (!signal.aborted && isCurrent()) this.messages.push(text);
  }
}

export class LiveSession {
  #tracker; #engine; #speech; #color; #job = null; #output = null; #serial = 0; #spoken = null; #movetimeMs; #timer; #stopped = false;
  lastError = null;
  constructor({engine, speech = new TextSpeechSink(), color, trackerOptions = {}, watchdogMs = 50, movetimeMs = 1000}) {
    if (!Number.isInteger(movetimeMs) || movetimeMs < 50 || movetimeMs > 3000) throw new Error('Invalid analysis time.');
    this.#movetimeMs = movetimeMs;
    if (typeof engine !== 'function' || !['w','b'].includes(color) || typeof speech.speak !== 'function' || typeof speech.cancel !== 'function' || !Number.isFinite(watchdogMs) || watchdogMs < 1) throw new Error('Invalid live adapters/options.');
    this.#tracker = new ObservationTracker(trackerOptions); this.#engine = engine; this.#speech = speech; this.#color = color;
    this.#timer = setInterval(() => { try { this.tick(); } catch { this.#cancel(); } }, watchdogMs);
    this.#timer.unref?.();
  }
  #key(s) { return JSON.stringify([s.sourceId,s.epoch,s.revision,s.fen]); }
  #cancel() { this.#serial++; this.#job?.controller.abort(); this.#output?.controller.abort(); this.#job = null; this.#output = null; this.#speech.cancel(); }
  connect(sourceId) { if (this.#stopped) throw new Error('Create a new session after stop.'); this.#cancel(); this.#spoken = null; return this.#tracker.connect(sourceId); }
  confirm(input) { this.#cancel(); this.#spoken = null; return this.#tracker.confirm(input); }
  stop() { this.#stopped = true; this.#cancel(); clearInterval(this.#timer); return this.#tracker.disconnect(); }
  tick() {
    const s = this.#tracker.snapshot();
    if ([this.#job, this.#output].some(activity => activity && (!s.guidanceAllowed || activity.key !== this.#key(s)))) this.#cancel();
    return s;
  }
  /** Only explicitly human-reviewed labeled rehearsal input is supported.
   * Never pass recognizer review drafts here without separate human review. */
  ingestReviewed(frame, {humanReviewed = false} = {}) {
    if (humanReviewed !== true) { this.#cancel(); this.#tracker.edit(); throw new Error('Separate human review of this labeled frame is required.'); }
    const s = this.#tracker.ingest(frame); this.tick(); return s;
  }
  async guide() {
    const s = this.tick(), key = this.#key(s);
    if (!s.guidanceAllowed || s.fen.split(' ')[1] !== this.#color || positionPayload(loadPosition(s.fen)).gameOver || this.#job || this.#spoken === key) return null;
    const controller = new AbortController(), serial = ++this.#serial;
    this.lastError = null;
    this.#job = {key,controller};
    const current = () => { const now = this.tick(); return !controller.signal.aborted && serial === this.#serial && now.guidanceAllowed && this.#key(now) === key; };
    try {
      const result = await this.#engine({fen:s.fen,confirmation:true,movetimeMs:this.#movetimeMs,requestId:key}, {signal:controller.signal});
      if (!current() || result.requestId !== key || result.fen !== s.fen || !result.bestMove) return null;
      const text = spokenMove(s.fen, result.bestMove);
      if (!current()) return null;
      // A speech adapter may resolve once audio is queued. Retain its identity
      // and abort signal after the engine job finishes so later invalidation
      // still stops queued or ongoing playback.
      this.#output = {key,controller};
      this.#spoken = key;
      await this.#speech.speak(text, {signal:controller.signal,isCurrent:current,identity:{sourceId:s.sourceId,epoch:s.epoch,revision:s.revision,fen:s.fen}});
      return current() ? {text,result} : null;
    } catch (error) {
      if (!controller.signal.aborted && serial === this.#serial) {
        this.lastError = error instanceof Error ? error.message : 'Live guidance failed.';
        if (this.#spoken === key) this.#spoken = null;
        this.#cancel();
      }
      return null;
    }
    finally { if (serial === this.#serial) this.#job = null; }
  }
}
