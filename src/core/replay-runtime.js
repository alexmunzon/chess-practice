/** Offline "Replay game" boundary: one DeviceGameSession behind a strict JSON
 * request/reply contract (docs/REPLAY_GAME.md). Tracking only: no engine, speech,
 * HTTP or device APIs, and replies never grant guidance or claim full history.
 * Time is a virtual replay clock driven only by accepted frame timestamps; this
 * module never reads a wall or monotonic host clock.
 */
import {DeviceGameSession} from './device-game-session.js';

export const REPLAY_CLOCK_DOMAIN = 'replay-synthetic-v1';
export const REPLAY_REPLY_KEYS = Object.freeze(['schemaVersion', 'requestId', 'kind', 'runtime', 'mode', 'session',
  'lastFrame', 'trackingReady', 'guidanceAllowed', 'liveGuidanceAllowed', 'state']);
export const REPLAY_ERROR_KEYS = Object.freeze(['schemaVersion', 'requestId', 'kind', 'runtime', 'mode',
  'guidanceAllowed', 'liveGuidanceAllowed', 'error']);
const KINDS = new Set(['initialize', 'observe', 'invalidate', 'snapshot']);
const TRACKER_KEYS = ['schemaVersion', 'requestId', 'kind', 'mode', 'clockDomain', 'session', 'lastFrame',
  'trackingReady', 'guidanceAllowed', 'liveGuidanceAllowed', 'state'];
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const identifier = value => typeof value === 'string' && /^[A-Za-z0-9_.:/-]{1,128}$/.test(value);
const time = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const failure = (message, code) => Object.assign(new Error(message), {code});

function peek(text) {
  // Best-effort echo for error replies only; the tracker performs the real validation.
  try {
    const value = typeof text === 'string' && text.length <= 16384 ? JSON.parse(text) : null;
    return record(value) ? value : null;
  } catch { return null; }
}

export class ReplayRuntime {
  #session; #virtualMs = 0; #candidateMs = null; #active = null;

  constructor() {
    // Clock read happens only after the tracker has fully validated a request.
    const replayClock = {clockDomain: REPLAY_CLOCK_DOMAIN, now: () => {
      if (this.#candidateMs !== null) this.#virtualMs = Math.max(this.#virtualMs, this.#candidateMs);
      this.#candidateMs = null;
      return this.#virtualMs;
    }};
    this.#session = new DeviceGameSession({replayClock});
  }

  /** Current virtual replay time in milliseconds (read-only, for diagnostics). */
  get virtualClockMs() { return this.#virtualMs; }

  /** Accepts one JSON request string, returns one JSON reply string. Synchronous:
   * a request is fully answered before the next can start. */
  handle(text) {
    const peeked = peek(text);
    const requestId = identifier(peeked?.requestId) ? peeked.requestId : null;
    const kind = KINDS.has(peeked?.kind) ? peeked.kind : null;
    const frame = kind === 'observe' && record(peeked.frame) ? peeked.frame : null;
    // Only frames claiming the active session may move virtual time forward.
    this.#candidateMs = frame && record(frame.identity) && this.#active &&
      frame.identity.sessionId === this.#active.sessionId && frame.identity.epoch === this.#active.epoch &&
      time(frame.capturedAtMs) ? frame.capturedAtMs : null;
    let reply;
    try {
      reply = this.#session.handle(text);
    } catch (error) {
      // DeviceGameSession revokes tracking before every throw.
      return this.#error(requestId, kind, error.code, error.message, true);
    } finally { this.#candidateMs = null; }
    try {
      return JSON.stringify(this.#map(reply));
    } catch (error) {
      return this.#error(requestId, kind, error.code, error.message, false);
    }
  }

  #map(reply) {
    const extra = Object.keys(reply).filter(key => !TRACKER_KEYS.includes(key));
    if (!TRACKER_KEYS.every(key => Object.hasOwn(reply, key)) ||
        extra.some(key => key !== 'ignored' && key !== 'invalidationReason') ||
        reply.mode !== 'replay-only' || reply.clockDomain !== REPLAY_CLOCK_DOMAIN ||
        reply.guidanceAllowed !== false || reply.liveGuidanceAllowed !== false ||
        typeof reply.trackingReady !== 'boolean' || !record(reply.state) || reply.state.historyComplete !== false) {
      throw failure('Tracker reply broke the replay contract.', 'INVALID_TRACKER_REPLY');
    }
    if (reply.ignored === 'stale-session') {
      // The tracker ignored it and stayed unchanged; surface it as a structured error.
      throw failure('Request belongs to a foreign or retired replay session.', 'STALE_SESSION');
    }
    if (reply.kind === 'initialize') this.#active = {...reply.session};
    const {status, reason, revision, fen, lastMove} = reply.state;
    return {schemaVersion: 1, requestId: reply.requestId, kind: reply.kind, runtime: 'on-device-local',
      mode: 'replay-only', session: reply.session, lastFrame: reply.lastFrame, trackingReady: reply.trackingReady,
      guidanceAllowed: false, liveGuidanceAllowed: false,
      state: {status, reason, revision, fen, lastMove, historyComplete: false},
      ...(typeof reply.ignored === 'string' ? {ignored: reply.ignored} : {})};
  }

  #error(requestId, kind, code, message, trackerRevoked) {
    return JSON.stringify({schemaVersion: 1, requestId, kind, runtime: 'on-device-local', mode: 'replay-only',
      guidanceAllowed: false, liveGuidanceAllowed: false,
      error: {code: typeof code === 'string' ? code : 'INVALID_REQUEST',
        message: String(message ?? 'Replay request failed.').slice(0, 512), trackerRevoked}});
  }
}
