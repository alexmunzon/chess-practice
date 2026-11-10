import { loadPosition, positionPayload } from './position.js';

export const SQUARES = Object.freeze(Array.from({ length: 64 }, (_, i) => 'abcdefgh'[i % 8] + (8 - Math.floor(i / 8))));
export const MAX_OBSERVATION_BYTES = 16384;
const labels = new Set(['empty', 'unknown', ...'PNBRQKpnbrqk']);
const record = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const finiteTime = v => typeof v === 'number' && Number.isFinite(v) && v >= 0;
const identity = v => typeof v === 'string' && /^[\w.:/-]{1,128}$/.test(v);
const exactKeys = (v, keys) => record(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));

/** Recognizer boundary: square coordinates are canonical (a1 is White's left corner).
 * This validates labels, not images. No classifier or capture device is implemented.
 */
export function validateObservation(frame) {
  if (!exactKeys(frame, ['sourceId', 'epoch', 'sequence', 'capturedAt', 'squares'])) throw new Error('Invalid observation fields.');
  if (!identity(frame.sourceId) || !Number.isSafeInteger(frame.epoch) || frame.epoch < 1 || !Number.isSafeInteger(frame.sequence) || frame.sequence < 0 || !finiteTime(frame.capturedAt)) throw new Error('Invalid observation identity, sequence, or monotonic time.');
  if (!exactKeys(frame.squares, SQUARES)) throw new Error('Exactly 64 canonical squares are required, including explicit unknowns.');
  for (const square of SQUARES) {
    const value = frame.squares[square];
    if (!exactKeys(value, ['label', 'confidence']) || !labels.has(value.label) || typeof value.confidence !== 'number' || !Number.isFinite(value.confidence) || value.confidence < 0 || value.confidence > 1) throw new Error(`Invalid square ${square}.`);
  }
  if (JSON.stringify(frame).length > MAX_OBSERVATION_BYTES) throw new Error('Observation is too large.');
  return structuredClone(frame);
}

function occupancy(chess) {
  return SQUARES.map(square => {
    const piece = chess.get(square);
    return piece ? (piece.color === 'w' ? piece.type.toUpperCase() : piece.type) : 'empty';
  }).join(',');
}

/** Fail-closed, zero/one legal ply tracker. Call snapshot/tick before using guidance.
 * All timestamps MUST share this tracker's monotonic clock domain, not Date.now().
 */
export class ObservationTracker {
  #clock; #options; #source = null; #epoch = 0; #chess = null; #confirmed = false;
  #sequence = -1; #capturedAt = -1; #lastSeen = null; #pending = null;
  #status = 'disconnected'; #reason = 'not-connected'; #revision = 0; #lastNow = -1; #lastMove = null;
  constructor({ clock = () => performance.now(), stableFrames = 2, stableMs = 50, timeoutMs = 1000, minConfidence = 0.95 } = {}) {
    if (typeof clock !== 'function' || !Number.isSafeInteger(stableFrames) || stableFrames < 2 || stableFrames > 30 || !finiteTime(stableMs) || !finiteTime(timeoutMs) || timeoutMs <= stableMs || !Number.isFinite(minConfidence) || minConfidence <= 0 || minConfidence > 1) throw new Error('Invalid tracker options.');
    this.#clock = clock; this.#options = { stableFrames, stableMs, timeoutMs, minConfidence };
  }
  #now() {
    const now = this.#clock();
    if (!finiteTime(now) || now < this.#lastNow) { this.#invalidate('invalid-clock'); throw new Error('Clock must be monotonic.'); }
    this.#lastNow = now; return now;
  }
  #invalidate(reason) { this.#confirmed = false; this.#pending = null; this.#status = this.#source ? 'needs-confirmation' : 'disconnected'; this.#reason = reason; this.#revision++; }
  #view() {
    return { status: this.#status, reason: this.#reason, sourceId: this.#source, epoch: this.#epoch, revision: this.#revision, guidanceAllowed: this.#status === 'ready', fen: this.#chess?.fen({ forceEnpassantSquare: true }) ?? null, lastMove: this.#lastMove ? { ...this.#lastMove } : null, historyComplete: false };
  }
  connect(sourceId) {
    if (!identity(sourceId)) throw new Error('Invalid source identity.');
    this.#now(); this.#source = sourceId; this.#epoch++; this.#sequence = -1; this.#capturedAt = -1; this.#lastSeen = null; this.#lastMove = null;
    this.#invalidate('source-connected'); return this.#view();
  }
  disconnect() { this.#source = null; this.#epoch++; this.#invalidate('disconnected'); return this.#view(); }
  edit() { this.#invalidate('manual-edit'); return this.#view(); }
  confirm({ fen, reviewed } = {}) {
    this.#invalidate('confirmation-required');
    if (!this.#source) throw new Error('Connect a source before confirming.');
    if (!exactKeys(reviewed, ['pieces', 'turn', 'castling', 'enPassant', 'counters']) || Object.values(reviewed).some(v => v !== true)) throw new Error('Human review of every FEN field is required.');
    this.#chess = loadPosition(fen); this.#lastMove = null; this.#confirmed = true; this.#lastSeen = this.#now();
    this.#status = 'stabilizing'; this.#reason = 'waiting-for-observations'; return this.#view();
  }
  tick() {
    const now = this.#now();
    if (this.#confirmed && this.#lastSeen !== null && now - this.#lastSeen > this.#options.timeoutMs) this.#invalidate('observation-timeout');
    return this.#view();
  }
  snapshot() { return this.tick(); }
  ingest(input) {
    const now = this.#now();
    this.tick();
    let frame;
    try { frame = validateObservation(input); } catch (error) { this.#invalidate('invalid-observation'); return { ...this.#view(), error: error.message }; }
    // Old connection callbacks are ignored, even if their source no longer exists.
    if (frame.epoch !== this.#epoch || !this.#source) return { ...this.#view(), ignored: 'stale-session' };
    if (frame.sourceId !== this.#source) { this.#invalidate('source-mismatch'); return this.#view(); }
    if (frame.sequence <= this.#sequence || frame.capturedAt <= this.#capturedAt) return { ...this.#view(), ignored: 'repeated-or-reordered-frame' };
    this.#sequence = frame.sequence; this.#capturedAt = frame.capturedAt;
    if (frame.capturedAt > now || now - frame.capturedAt > this.#options.timeoutMs) { this.#invalidate('stale-or-future-frame'); return this.#view(); }
    if (!this.#confirmed) return this.#view();
    // A fresh callback from before the human's confirmation cannot establish stability.
    if (frame.capturedAt < this.#lastSeen && this.#reason === 'waiting-for-observations') return { ...this.#view(), ignored: 'before-confirmation' };
    this.#lastSeen = frame.capturedAt;
    const cells = SQUARES.map(square => frame.squares[square]);
    if (cells.some(cell => cell.label === 'unknown' || cell.confidence < this.#options.minConfidence)) { this.#invalidate('uncertain-squares'); return this.#view(); }
    const key = cells.map(cell => cell.label).join(',');
    // A fresh observation of the same already-stable board extends freshness,
    // without starving asynchronous analysis under a continuous frame stream.
    if (this.#status === 'ready' && occupancy(this.#chess) === key) return this.#view();
    this.#revision++; this.#status = 'stabilizing'; this.#reason = 'waiting-for-stability';
    const candidates = [];
    if (occupancy(this.#chess) === key) candidates.push(null);
    if (!positionPayload(this.#chess).gameOver) for (const move of this.#chess.moves({ verbose: true })) {
      this.#chess.move(move);
      if (occupancy(this.#chess) === key) candidates.push({ from: move.from, to: move.to, ...(move.promotion ? { promotion: move.promotion } : {}), san: move.san });
      this.#chess.undo();
    }
    if (candidates.length !== 1) { this.#invalidate(candidates.length ? 'ambiguous-observation' : 'not-zero-or-one-legal-move'); return this.#view(); }
    if (this.#pending?.key === key) this.#pending.count++;
    else this.#pending = { key, count: 1, firstAt: frame.capturedAt };
    if (this.#pending.count >= this.#options.stableFrames && frame.capturedAt - this.#pending.firstAt >= this.#options.stableMs) {
      if (candidates[0]) { this.#chess.move(candidates[0]); this.#lastMove = candidates[0]; }
      this.#status = 'ready'; this.#reason = 'stable-legal-position';
    }
    return this.#view();
  }
}
