/** Standalone replay-only continuity bridge. No engine, speech, HTTP or device APIs.
 * The caller owns the review UI; a checklist is required, never manufactured here.
 * Drafts may remain outside this object while being reviewed. initialize starts
 * freshness at review time, then new, stable matching pixels establish readiness.
 * DAT PTS/receipt time must never be relabeled as this trusted replay clock.
 */
import {ObservationTracker, validateObservation} from './observation.js';
import {loadPosition} from './position.js';

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const exact = (value, keys) => record(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const identifier = value => typeof value === 'string' && /^[A-Za-z0-9_.:/-]{1,128}$/.test(value);
const integer = (value, minimum = 0) => Number.isSafeInteger(value) && value >= minimum;
const failure = (message, code = 'INVALID_REQUEST') => Object.assign(new Error(message), {code});
const reviewedFields = ['pieces', 'turn', 'castling', 'enPassant', 'counters'];
const reasons = new Set(['manual-edit', 'interrupted', 'background', 'reset', 'disconnect']);

function sessionIdentity(value) {
  if (!exact(value, ['sessionId', 'epoch']) || !identifier(value.sessionId) || !integer(value.epoch, 1)) {
    throw failure('Invalid replay session identity.');
  }
  return Object.freeze({...value});
}

function command(text, clockDomain) {
  if (typeof text !== 'string' || text.length > 16384) throw failure('Expected a bounded JSON command.');
  let value;
  try { value = JSON.parse(text); } catch { throw failure('Malformed replay command JSON.'); }
  const fields = {
    initialize: ['session', 'fen', 'reviewed'], observe: ['frame'],
    invalidate: ['session', 'reason'], snapshot: ['session']
  };
  if (!record(value) || value.schemaVersion !== 1 || !identifier(value.requestId) ||
      typeof value.kind !== 'string' || !Object.hasOwn(fields, value.kind) ||
      !exact(value, ['schemaVersion', 'requestId', 'kind', 'mode', 'clockDomain', ...fields[value.kind]])) {
    throw failure('Invalid replay command envelope.');
  }
  if (value.mode !== 'trusted-replay' || value.clockDomain !== clockDomain) {
    throw failure('An explicit matching trusted replay clock domain is required.', 'CLOCK_DOMAIN_MISMATCH');
  }
  if (value.kind === 'observe') {
    const frame = value.frame;
    if (!exact(frame, ['identity', 'capturedAtMs', 'squares']) ||
        !exact(frame.identity, ['sessionId', 'epoch', 'sequence', 'frameSha256']) ||
        !integer(frame.identity.sequence) || !integer(frame.capturedAtMs) || typeof frame.identity.frameSha256 !== 'string' ||
        !/^[a-f0-9]{64}$/.test(frame.identity.frameSha256)) throw failure('Invalid replay frame identity.');
    value.session = sessionIdentity({sessionId: frame.identity.sessionId, epoch: frame.identity.epoch});
    validateObservation({sourceId: value.session.sessionId, epoch: value.session.epoch,
      sequence: frame.identity.sequence, capturedAt: frame.capturedAtMs, squares: frame.squares});
    frame.identity = Object.freeze({...frame.identity});
  } else value.session = sessionIdentity(value.session);
  if (value.kind === 'initialize') {
    if (!exact(value.reviewed, reviewedFields) || Object.values(value.reviewed).some(checked => checked !== true)) {
      throw failure('Explicit review of every complete-state field is required.', 'CONFIRMATION_REQUIRED');
    }
    loadPosition(value.fen); // Six fields are required; no historical defaults.
  }
  if (value.kind === 'invalidate' && !reasons.has(value.reason)) throw failure('Unsupported invalidation reason.');
  return value;
}

export class DeviceGameSession {
  #tracker; #clock; #clockDomain; #lastNow = -Infinity;
  #session = null; #internalEpoch = 0; #lastFrame = null;
  #busy = false; #generation = 0;

  constructor({replayClock} = {}) {
    if (!record(replayClock) || !identifier(replayClock.clockDomain) || typeof replayClock.now !== 'function') {
      throw new TypeError('An explicit trusted replay clock provider and domain are required.');
    }
    this.#clockDomain = replayClock.clockDomain;
    const now = replayClock.now;
    this.#clock = () => now.call(replayClock);
    // Production defaults remain unchanged: two frames, 50ms stability, 1s freshness.
    this.#tracker = new ObservationTracker({clock: () => this.#readClock()});
  }

  #readClock() {
    const generation = this.#generation;
    let now;
    try { now = this.#clock(); } catch { throw failure('Replay clock failed.', 'INVALID_CLOCK'); }
    if (generation !== this.#generation) throw failure('Reentrant replay command revoked this operation.', 'ABORTED');
    if (!Number.isSafeInteger(now) || now < 0 || now < this.#lastNow) {
      throw failure('Replay clock must be a safe integer, nonnegative and monotonic.', 'INVALID_CLOCK');
    }
    this.#lastNow = now;
    return now;
  }

  #revoke() { this.#generation++; this.#tracker.edit(); }
  #matches(session) { return this.#session?.sessionId === session.sessionId && this.#session.epoch === session.epoch; }
  #reply(request, state, extra = {}) {
    return {schemaVersion: 1, requestId: request.requestId, kind: request.kind, mode: 'replay-only',
      clockDomain: this.#clockDomain, session: this.#session ? {...this.#session} : null,
      lastFrame: this.#lastFrame ? {...this.#lastFrame.identity, capturedAtMs: this.#lastFrame.capturedAtMs} : null,
      trackingReady: state.guidanceAllowed, guidanceAllowed: false, liveGuidanceAllowed: false,
      state: {status: state.status, reason: state.reason, revision: state.revision, fen: state.fen,
        lastMove: state.lastMove, historyComplete: false}, ...extra};
  }

  /** Exact JSON only snapshots the caller's input. Returns tracking state only,
   * never an engine/speech permit, even when replay observations are ready. */
  handle(text) {
    if (this.#busy) { this.#revoke(); throw failure('Reentrant replay command.', 'ABORTED'); }
    this.#busy = true;
    const generation = this.#generation;
    try {
      const request = command(text, this.#clockDomain);
      let state, extra = {};
      if (request.kind === 'initialize') {
        if (this.#session && (request.session.epoch < this.#session.epoch ||
            (request.session.epoch === this.#session.epoch && !this.#matches(request.session)))) {
          throw failure('Review belongs to a retired replay session.', 'STALE_IDENTITY');
        }
        if (!this.#matches(request.session)) {
          this.#internalEpoch = this.#tracker.connect(request.session.sessionId).epoch;
          this.#session = request.session; this.#lastFrame = null;
        }
        state = this.#tracker.confirm({fen: request.fen, reviewed: request.reviewed});
      } else {
        if (!this.#session) throw failure('Initialize with explicit full-state review first.', 'INITIALIZATION_REQUIRED');
        if (!this.#matches(request.session)) {
          // Old callbacks do not mutate or refresh the active session.
          state = this.#tracker.snapshot(); extra = {ignored: 'stale-session'};
        } else if (request.kind === 'invalidate') {
          state = this.#tracker.edit(); extra = {invalidationReason: request.reason};
        } else if (request.kind === 'snapshot') state = this.#tracker.snapshot();
        else {
          const frame = request.frame, previous = this.#lastFrame;
          if (previous && frame.identity.sequence === previous.identity.sequence &&
              (frame.identity.frameSha256 !== previous.identity.frameSha256 || frame.capturedAtMs !== previous.capturedAtMs)) {
            throw failure('An existing frame sequence changed its immutable identity.', 'FRAME_IDENTITY_CONFLICT');
          }
          state = this.#tracker.ingest({sourceId: request.session.sessionId, epoch: this.#internalEpoch,
            sequence: frame.identity.sequence, capturedAt: frame.capturedAtMs, squares: frame.squares});
          if (state.ignored) extra = {ignored: state.ignored};
          else this.#lastFrame = {identity: frame.identity, capturedAtMs: frame.capturedAtMs};
        }
      }
      if (generation !== this.#generation) throw failure('Replay operation was revoked.', 'ABORTED');
      return this.#reply(request, state, extra);
    } catch (error) {
      this.#revoke();
      throw error;
    } finally { this.#busy = false; }
  }
}
