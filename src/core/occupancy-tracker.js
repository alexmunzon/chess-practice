/** Occupancy game tracker (pure logic, no images, no clock, no randomness). docs/OCCUPANCY_TRACKER.md
 *
 * Each picture reads every square only as empty / white / black / unknown. `inferMove` names the one
 * legal move (or "unchanged") that explains the picture against the tracked FEN. Same safety contract
 * as ObservationTracker: a position is trusted only after a full human review (`confirm`) plus legally
 * tracked moves; anything unexplained, uncertain for too long, interrupted or out of order REVOKES
 * until a new `confirm`; nothing late or stale can restore it.
 *
 * Promotion: occupancy cannot see which piece a pawn became, so after agreeFrames pictures agree on the
 * same promotion squares the tracker asks ONE question (`awaiting-promotion-choice`) and accepts exactly
 * one answer (q, r, b or n) carrying that question's id; then it verifies the new position before trusting it.
 *
 * Time comes only from `capturedAtMs`, `tick(atMs)`, `confirm({atMs})` and `answerPromotion({atMs})`.
 */
import { inferMove, occupancyFromFen, OCCUPANCY_SQUARES } from './occupancy-move-inference.js';
import { loadPosition } from './position.js';

export const OCCUPANCY_LABELS = Object.freeze(['empty', 'white', 'black', 'unknown']);
export const PROMOTION_PIECES = Object.freeze(['q', 'r', 'b', 'n']);
export const TRACKER_STATUSES = Object.freeze(['needs-confirmation', 'verifying', 'ready', 'confirming-change', 'awaiting-promotion-choice']);
const REVIEW_FIELDS = ['pieces', 'turn', 'castling', 'enPassant', 'counters'];
const LABELS = new Set(OCCUPANCY_LABELS);
const SEEN_HASH_LIMIT = 8192; // about 14 minutes of pictures at 10 per second
const record = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const exact = (v, keys) => record(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const identifier = v => typeof v === 'string' && /^[A-Za-z0-9_.:/-]{1,128}$/.test(v);
const int = (v, min = 0) => Number.isSafeInteger(v) && v >= min;
const failure = (message, code) => Object.assign(new Error(message), { code });
/** Same definition as positionPayload(...).gameOver, without building SAN for every legal move. */
export const isGameOver = chess => chess.isCheckmate() || chess.isStalemate() || chess.isInsufficientMaterial() || Number(chess.fen().split(' ')[4]) >= 150;
// instanceIds already used in this JavaScript realm. Uniqueness across processes is the caller's job (see the doc).
const USED_INSTANCE_IDS = new Set();

function validateSession(value) {
  if (!exact(value, ['sessionId', 'epoch']) || !identifier(value.sessionId) || !int(value.epoch, 1)) throw failure('Invalid session identity.', 'INVALID_REQUEST');
  return { sessionId: value.sessionId, epoch: value.epoch };
}

/** Plain-data copy of a caller's input (own enumerable keys of plain records, three levels deep): every field is read
 * exactly once, so a getter or proxy cannot show one value to validation and another to the tracker afterwards. */
function plain(value, depth = 3) {
  if (!record(value)) return value;
  const out = Object.create(null); // an own "__proto__" key stays an own key (and so fails the exact-keys check)
  for (const key of Object.keys(value)) { const v = value[key]; out[key] = depth > 1 ? plain(v, depth - 1) : v; }
  return out;
}

/** Validates one occupancy picture; throws on any malformed field. Returns a frozen copy. */
export function validateOccupancyFrame(input) {
  const frame = plain(input);
  if (!exact(frame, ['identity', 'capturedAtMs', 'squares'])) throw new Error('Picture must have exactly identity, capturedAtMs, squares.');
  const id = frame.identity;
  if (!exact(id, ['sessionId', 'epoch', 'sequence', 'frameSha256']) || !identifier(id.sessionId) || !int(id.epoch, 1) || !int(id.sequence) ||
      typeof id.frameSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(id.frameSha256)) throw new Error('Invalid picture identity.');
  if (!int(frame.capturedAtMs)) throw new Error('capturedAtMs must be a nonnegative safe integer.');
  if (!exact(frame.squares, OCCUPANCY_SQUARES)) throw new Error('Exactly 64 named squares are required, including explicit unknowns.');
  const squares = {};
  for (const square of OCCUPANCY_SQUARES) {
    const cell = frame.squares[square];
    if (!exact(cell, ['label', 'confidence']) || !LABELS.has(cell.label) || typeof cell.confidence !== 'number' || !Number.isFinite(cell.confidence) || cell.confidence < 0 || cell.confidence > 1) throw new Error(`Invalid square ${square}.`);
    squares[square] = { label: cell.label, confidence: cell.confidence };
  }
  return Object.freeze({ identity: Object.freeze({ ...id }), capturedAtMs: frame.capturedAtMs, squares: Object.freeze(squares) });
}

/**
 * In transit: versus the tracked occupancy, exactly ONE square holding a piece of the side to move reads empty, at most
 * ONE other square reads unknown, and every other square reads as before. Returns the lifted square's index or -1.
 * (Used with any number of unknowns only to set the lift memory of an unusable picture; see ingest.)
 */
export function liftedSquare(base, observed, sideToMove, maxUnknown = 1) {
  let lifted = -1, unknown = 0;
  for (let i = 0; i < 64; i++) {
    if (observed[i] === base[i]) continue;
    if (observed[i] === 'unknown') { if (++unknown > maxUnknown) return -1; continue; }
    if (base[i] === sideToMove && observed[i] === 'empty' && lifted < 0) { lifted = i; continue; }
    return -1;
  }
  return lifted;
}

// Rook moves that are also the first half of a castling still allowed by the FEN (rook-first castling looks exactly like them).
const CASTLING_ROOK = { h1f1: 'K', a1d1: 'Q', h8f8: 'k', a8d8: 'q' };
const castlingRookShaped = (fen, move) => Boolean(CASTLING_ROOK[move.from + move.to]) && fen.split(' ')[2].includes(CASTLING_ROOK[move.from + move.to]);

export class OccupancyTracker {
  #o; #session = null; #clock = 0; #lastFrame = null; #seenHashes = new Set(); #verifyReason = null;
  #status = 'needs-confirmation'; #reason = 'not-confirmed'; #revision = 0;
  #fen = null; #terminal = false; #confirmedAt = null; #lastUsableAt = null; #skipped = 0;
  #pending = null; #question = null; #questionCounter = 0; #lastAnsweredId = null;
  #lastMove = null; #movesAccepted = 0; #baseOcc = null; #lift = null;
  // Since the last completed agreement (or confirm): squares any picture showed differently from the expected occupancy
  // (unknown included), the subset that read unknown (hidden), and whether any picture showed a definite change. See #swapPossible.
  #disturbed = new Set(); #hidden = new Set(); #changeSeen = false;
  // Rank-1 and rank-8 readings since the last completed agreement (castling check), the capture time of the last picture
  // that showed the board (gap check), and whether a picture was recorded since the last confirm (sequence check).
  #rankPatterns = new Set(); #lastSeenAt = null; #seenSinceConfirm = false;

  /**
   * `instanceId` (required): unique per tracker; goes into every question id. Reusing one in the same realm throws.
   * agreeFrames is at least 2 by every route (a single-picture rule accepted wrong moves in simulation).
   * minSettleMs: the agreeing pictures of a MOVE must span at least this long, so a piece touched down in passing is not taken.
   * castlingRookSettleMs: the longer span for a rook move that is also the first half of an allowed castling.
   * inTransitTolerance (default false): a lifted piece is skipped like an unusable picture instead of revoking.
   * readyDwellMs (default 1000): a move is accepted (and the tracker ready) only after the new position has stayed in view, in
   * agreeing pictures, for at least this long, so a piece resting on a square on its way is not taken for a played move.
   * maxPictureGapMs (default 250): while confirmed, two consecutive pictures (or the review and the first picture) further
   * apart than this revoke: the board was not watched, so pieces may have been exchanged unseen.
   */
  constructor({ instanceId, agreeFrames = 2, minFrameGapMs = 50, minSettleMs = 300, castlingRookSettleMs = 1500, maxSilenceMs = 1000, minConfidence = 0.95, maxSkippedUnusable = 2,
    promotionTimeoutMs = 20000, inTransitTolerance = false, readyDwellMs = 1000, maxPictureGapMs = 250 } = {}) {
    if (!identifier(instanceId) || !int(agreeFrames, 2) || agreeFrames > 10 || !int(minFrameGapMs) || !int(minSettleMs) || !int(castlingRookSettleMs) || castlingRookSettleMs < minSettleMs || !int(maxSilenceMs, 1) ||
        maxSilenceMs <= minFrameGapMs || minSettleMs >= maxSilenceMs || typeof minConfidence !== 'number' || !(minConfidence > 0 && minConfidence <= 1) ||
        !int(maxSkippedUnusable) || maxSkippedUnusable > 100 || !int(promotionTimeoutMs, 1) || typeof inTransitTolerance !== 'boolean' || !int(readyDwellMs) || !int(maxPictureGapMs, 1) || maxPictureGapMs > maxSilenceMs) throw new Error('Invalid occupancy tracker options.');
    if (USED_INSTANCE_IDS.has(instanceId)) throw new Error('instanceId already used by another tracker in this process.');
    USED_INSTANCE_IDS.add(instanceId);
    this.#o = Object.freeze({ instanceId, agreeFrames, minFrameGapMs, minSettleMs, castlingRookSettleMs, maxSilenceMs, minConfidence, maxSkippedUnusable, promotionTimeoutMs, inTransitTolerance, readyDwellMs, maxPictureGapMs });
  }

  get options() { return this.#o; }

  #revoke(reason) {
    this.#status = 'needs-confirmation'; this.#reason = reason; this.#revision++;
    this.#fen = null; this.#terminal = false; this.#confirmedAt = null; this.#lastUsableAt = null; this.#skipped = 0;
    this.#pending = null; this.#question = null; this.#lastMove = null; this.#lift = null; this.#settled();
    this.#lastSeenAt = null; this.#seenSinceConfirm = false;
  }
  /** An agreement completed (or the tracker revoked): disturbance evidence starts again from here. */
  #settled() { this.#disturbed.clear(); this.#hidden.clear(); this.#changeSeen = false; this.#rankPatterns.clear(); }
  /**
   * Castling moves two pieces of the same colour, so its four squares alone cannot show which piece went where (rook h1-g1
   * then king e1-f1 ends with the same occupancy as O-O). It is accepted only if every picture since the last completed
   * agreement showed those four squares exactly as before, as after the rook-first half, or as after castling; anything else
   * there (another move shape, an unknown square) could have been a different sequence of piece movements: revoke.
   */
  #castlingSeenSafely(fenBefore, fenAfter, move) {
    const rank = move.from[1], kingside = move.to[0] === 'g', rookFrom = (kingside ? 'h' : 'a') + rank, rookTo = (kingside ? 'f' : 'd') + rank;
    const files = [move.from, move.to, rookFrom, rookTo].map(sq => 'abcdefgh'.indexOf(sq[0]));
    const before = occupancyFromFen(fenBefore), after = occupancyFromFen(fenAfter), r0 = (Number(rank) - 1) * 8;
    const cut = row => files.map(f => row[f]).join(',');
    const half = before.slice(r0, r0 + 8); half[files[2]] = 'empty'; half[files[3]] = before[r0 + files[0]];
    const allowed = new Set([cut(before.slice(r0, r0 + 8)), cut(after.slice(r0, r0 + 8)), cut(half)]);
    for (const pattern of this.#rankPatterns) if (pattern.startsWith(`${rank}:`) && !allowed.has(cut(pattern.slice(2).split(',')))) return false;
    return true;
  }
  /**
   * Could pieces have been exchanged behind the pictures since the last completed agreement? `fenBefore` is the position
   * the run started from, `fenAfter` the one about to be trusted. A piece can only have moved if its square was disturbed in
   * some picture. The squares the legal move itself changes are taken to follow the move; any OTHER disturbed square that
   * holds a piece (of either side) afterwards could hold a different piece of the same colour, so it revokes.
   * Round 5 revoked only when the disturbed squares held two or more piece types of that colour. Round 7 (rule R1, either
   * colour): the partner need not have been disturbed in any picture. It can trade squares entirely inside one picture gap,
   * or come from off the board (a spare or captured piece), for the side that moved and for the opponent alike.
   * Round 7b: a square the move changes is excused, except a CAPTURED piece's square that read unknown in some picture: the
   * piece there may have traded places with another piece of its colour while hidden, so the piece taken off the board may
   * not be the one the tracker would remove. A hand covering that square while the capture is in progress reads the same
   * as that trade, so it revokes too (the price of the rule).
   * Not covered: the moving piece itself (traded or substituted between two pictures), and any exchange completed between two
   * consecutive pictures with nothing read differently (see the doc).
   */
  #swapPossible(fenBefore, fenAfter) {
    if (!this.#disturbed.size) return false;
    const occBefore = occupancyFromFen(fenBefore), occAfter = fenAfter === fenBefore ? occBefore : occupancyFromFen(fenAfter);
    const opponent = fenBefore.split(' ')[1] === 'w' ? 'black' : 'white';
    for (const i of this.#disturbed) {
      if (occBefore[i] !== occAfter[i]) {
        if (occBefore[i] === opponent && this.#hidden.has(i)) return true; // captured piece hidden before it was taken
        continue; // a square the move itself changes
      }
      if (occAfter[i] !== 'empty') return true; // a piece of either side that may have been exchanged unseen
    }
    return false;
  }
  #set(status, reason) { this.#status = status; this.#reason = reason; this.#revision++; }
  #confirmed() { return this.#status !== 'needs-confirmation'; }
  #advanceClock(atMs) { this.#clock = Math.max(this.#clock, atMs); }
  #tooFarAhead(atMs) { return atMs > this.#clock + this.#o.maxSilenceMs; }
  /** Silence and promotion watchdogs at time `t` (does not move the clock). Returns true if it revoked. */
  #watchdogs(t) {
    if (!this.#confirmed()) return false;
    if (t - this.#lastUsableAt > this.#o.maxSilenceMs) { this.#revoke('observation-timeout'); return true; }
    if (this.#question && t - this.#question.askedAtMs > this.#o.promotionTimeoutMs) { this.#revoke('promotion-timeout'); return true; }
    return false;
  }
  #setFen(fen) { this.#fen = fen; this.#terminal = isGameOver(loadPosition(fen)); }
  #base() {
    if (this.#baseOcc?.fen !== this.#fen) this.#baseOcc = { fen: this.#fen, occ: occupancyFromFen(this.#fen), side: this.#fen.split(' ')[1] === 'w' ? 'white' : 'black' };
    return this.#baseOcc;
  }

  /** State for callers. `fen` and `lastMove` are non-null ONLY while trackingReady is true. With `atMs` (the current time
   * in the camera's clock) the silence and promotion watchdogs run first, exactly as `tick(atMs)`; without it the reply is
   * only as fresh as the last picture or tick (the tracker has no clock of its own). */
  snapshot(...args) {
    if (args.length) this.tick(args[0]);
    return this.#view();
  }
  #view() {
    const ready = this.#status === 'ready', q = this.#question;
    return {
      status: this.#status, reason: this.#reason, revision: this.#revision,
      trackingReady: ready, guidanceAllowed: false, historyComplete: false,
      fen: ready ? this.#fen : null, lastMove: ready && this.#lastMove ? { ...this.#lastMove } : null,
      movesAccepted: this.#movesAccepted,
      session: this.#session ? { ...this.#session } : null,
      lastFrame: this.#lastFrame ? { ...this.#lastFrame } : null,
      virtualClockMs: this.#clock,
      agreement: this.#pending ? { count: this.#pending.count, needed: this.#o.agreeFrames } : null,
      skippedUnusable: this.#skipped, liftedSquare: this.#lift === null ? null : OCCUPANCY_SQUARES[this.#lift],
      pendingQuestion: q ? { questionId: q.questionId, from: q.from, to: q.to, color: q.color, options: [...PROMOTION_PIECES],
        sanByPiece: Object.fromEntries(PROMOTION_PIECES.map(p => [p, q.candidates[p].san])), askedAtMs: q.askedAtMs,
        expiresAtMs: q.askedAtMs + this.#o.promotionTimeoutMs } : null,
    };
  }
  #out(event, extra = {}) { return { ...this.#view(), event, ...extra }; }

  /** Full human review. Always revokes first; on any error stays revoked and throws. `atMs` may move the clock any distance:
   * it is the explicit resynchronisation point after a pause. */
  confirm(raw) {
    this.#revoke('confirmation-required');
    try {
      const input = plain(raw);
      if (!exact(input, ['session', 'fen', 'reviewed']) && !exact(input, ['session', 'fen', 'reviewed', 'atMs'])) throw failure('confirm needs exactly session, fen, reviewed (and optional atMs).', 'INVALID_REQUEST');
      const session = validateSession(input.session);
      if (this.#session && (session.epoch < this.#session.epoch || (session.epoch === this.#session.epoch && session.sessionId !== this.#session.sessionId))) {
        throw failure('Review belongs to a retired session.', 'STALE_IDENTITY');
      }
      if (!exact(input.reviewed, REVIEW_FIELDS) || Object.values(input.reviewed).some(v => v !== true)) throw failure('Human review of every FEN field is required.', 'CONFIRMATION_REQUIRED');
      if (Object.hasOwn(input, 'atMs') && !int(input.atMs)) throw failure('atMs must be a nonnegative safe integer.', 'INVALID_REQUEST');
      const fen = loadPosition(input.fen).fen({ forceEnpassantSquare: true }); // six fields required, legality checked
      if (!this.#session || this.#session.sessionId !== session.sessionId || this.#session.epoch !== session.epoch) { this.#session = session; this.#lastFrame = null; this.#seenHashes.clear(); }
      if (Object.hasOwn(input, 'atMs')) this.#advanceClock(input.atMs);
      this.#setFen(fen); this.#confirmedAt = this.#clock; this.#lastUsableAt = this.#clock; this.#lastSeenAt = this.#clock;
      this.#verifyReason = 'confirmed-position-seen';
      this.#set('verifying', 'waiting-to-see-confirmed-position');
      return this.#out('confirmed');
    } catch (error) {
      this.#revoke(error.code === 'STALE_IDENTITY' ? 'stale-review' : 'invalid-confirmation');
      throw error;
    }
  }

  /** Explicit interruption (manual edit, app background, reset, disconnect...). Always revokes. */
  invalidate(reason) {
    this.#revoke(identifier(reason) ? `invalidated:${reason}` : 'invalidated');
    return this.#out('revoked');
  }
  /** Same as invalidate('manual-edit') / invalidate('connected'): the method names the older ObservationTracker's callers
   * use, so an adapter that still calls them revokes instead of throwing. Arguments are ignored. */
  edit() { return this.invalidate('manual-edit'); }
  connect() { return this.invalidate('connected'); }

  /** Advance virtual time without a picture (runs watchdogs). Malformed time throws and revokes; a jump of more than
   * maxSilenceMs revokes and leaves the clock where it was. Round 7: the picture-gap rule applies here too, so a feed that
   * stops is revoked once the clock is more than maxPictureGapMs past the last picture that showed the board. */
  tick(atMs) {
    if (!int(atMs)) { this.#revoke('invalid-time'); throw failure('tick needs a nonnegative safe integer.', 'INVALID_REQUEST'); }
    if (this.#tooFarAhead(atMs)) { this.#revoke('observation-timeout'); return this.#out('revoked', { error: 'tick jumped further ahead than maxSilenceMs.' }); }
    this.#advanceClock(atMs);
    if (this.#watchdogs(this.#clock)) return this.#out('revoked');
    if (this.#confirmed() && this.#clock - this.#lastSeenAt > this.#o.maxPictureGapMs) { this.#revoke('picture-gap'); return this.#out('revoked'); }
    return this.#out('tick');
  }

  ingest(input) {
    let frame;
    try { frame = validateOccupancyFrame(input); } catch (error) { this.#revoke('invalid-observation'); return this.#out('revoked', { error: error.message }); }
    const { identity: id, capturedAtMs: t } = frame;
    // Foreign or retired session/epoch: ignored, never revokes, never moves time.
    if (!this.#session || id.sessionId !== this.#session.sessionId || id.epoch !== this.#session.epoch) return this.#out('ignored', { ignored: 'foreign-session' });
    const prev = this.#lastFrame;
    if (prev && id.sequence === prev.sequence) {
      if (id.frameSha256 === prev.frameSha256 && t === prev.capturedAtMs) return this.#out('ignored', { ignored: 'repeated-frame' });
      this.#revoke('frame-identity-conflict');
      return this.#out('revoked', { error: 'An existing picture sequence changed its hash or time.' });
    }
    // While confirmed, every picture after the first must be the next one in sequence and later in time: a picture that arrives
    // out of order, or a missing sequence number, means the tracker did not see the board in order, so it revokes.
    const live = this.#confirmed() && this.#seenSinceConfirm;
    if (prev && (id.sequence < prev.sequence || t <= prev.capturedAtMs)) {
      if (live) { this.#revoke('reordered-picture'); return this.#out('revoked'); }
      return this.#out('ignored', { ignored: 'repeated-or-reordered-frame' });
    }
    if (live && id.sequence !== prev.sequence + 1) { this.#revoke('missing-picture'); return this.#out('revoked'); }
    // Forward jump bound = maxSilenceMs (a longer gap would revoke for silence anyway). Not recorded, clock not moved.
    if (this.#tooFarAhead(t)) {
      if (!this.#confirmed()) return this.#out('ignored', { ignored: 'future-frame' });
      this.#revoke('observation-timeout'); return this.#out('revoked', { error: 'Picture time jumped further ahead than maxSilenceMs.' });
    }
    this.#lastFrame = { sequence: id.sequence, frameSha256: id.frameSha256, capturedAtMs: t };
    if (t < this.#clock - this.#o.maxSilenceMs) { this.#revoke('stale-frame'); return this.#out('revoked'); }
    this.#advanceClock(t);
    // The same image under a new sequence (frozen or replayed feed) is never evidence twice; it does not refresh the watchdog.
    const duplicate = this.#seenHashes.has(id.frameSha256);
    if (!duplicate) {
      this.#seenHashes.add(id.frameSha256);
      if (this.#seenHashes.size > SEEN_HASH_LIMIT) this.#seenHashes.delete(this.#seenHashes.values().next().value);
    }
    if (!this.#confirmed()) return this.#out('ignored', { ignored: 'not-confirmed' });
    this.#seenSinceConfirm = true;
    if (this.#watchdogs(t)) return this.#out('revoked');
    if (t - this.#lastSeenAt > this.#o.maxPictureGapMs) { this.#revoke('picture-gap'); return this.#out('revoked'); }
    // Evidence only: a picture taken before the confirm / promotion answer, or an image already seen (frozen or replayed feed).
    // It never counts toward agreement or refreshes the silence timer, but it feeds the disturbance memory and every revoke
    // check below. A repeated image does not count as having watched the board (gap check).
    const evidenceOnly = duplicate ? 'duplicate-frame' : t < this.#confirmedAt ? 'before-confirmation' : null;
    if (!duplicate) this.#lastSeenAt = t;

    const occupancy = OCCUPANCY_SQUARES.map(sq => {
      const cell = frame.squares[sq];
      return cell.label === 'unknown' || cell.confidence < this.#o.minConfidence ? 'unknown' : cell.label;
    });
    const q = this.#question;
    const result = inferMove({ fen: q ? q.fenBefore : this.#fen, occupancy });
    // In transit (opt-in): one own piece lifted. Not while a question is open (any change there means the game moved on).
    // An unusable picture that shows one own piece lifted (and its destination hidden) also sets the lift memory, in both modes.
    let lifted = -1;
    if (!q && (result.status === 'uncertain' || (result.status === 'no-legal-explanation' && this.#o.inTransitTolerance))) {
      const base = this.#base();
      lifted = liftedSquare(base.occ, occupancy, base.side, result.status === 'uncertain' ? 64 : 1);
    }
    const transit = result.status === 'no-legal-explanation' && lifted >= 0;
    // Known squares already contradict every legal hypothesis: unexplained change or misread.
    if (result.status === 'no-legal-explanation' && !transit) { this.#revoke(q ? 'changed-while-awaiting-promotion' : 'no-legal-explanation'); return this.#out('revoked'); }
    // Disturbance evidence (every kept picture, usable or not): squares that differ from what the tracked position (or the open
    // promotion's position) shows, and whether any difference was a definite reading rather than "unknown".
    const expected = q ? q.occAfter : this.#base().occ;
    for (let i = 0; i < 64; i++) if (occupancy[i] !== expected[i]) { this.#disturbed.add(i); if (occupancy[i] !== 'unknown') this.#changeSeen = true; else this.#hidden.add(i); }
    this.#rankPatterns.add(`1:${occupancy.slice(0, 8).join(',')}`); this.#rankPatterns.add(`8:${occupancy.slice(56, 64).join(',')}`);
    if (result.status === 'uncertain' || transit) {
      if (lifted >= 0) {
        // Lifted-square memory: during one run of skipped pictures only ONE square may be lifted (two would allow a swap).
        if (this.#lift !== null && this.#lift !== lifted) { this.#revoke('different-piece-lifted'); return this.#out('revoked'); }
        this.#lift = lifted;
      }
      // Skipped picture: never advances, never refreshes the silence timer, and voids any agreement collected before it
      // (a hand may have changed something we could not see).
      this.#skipped++;
      if (this.#skipped > this.#o.maxSkippedUnusable) { this.#revoke(this.#o.maxSkippedUnusable === 0 ? 'uncertain-squares' : 'too-many-unusable-pictures'); return this.#out('revoked'); }
      this.#pending = null;
      if (this.#status === 'ready') this.#set('confirming-change', transit ? 'piece-in-transit' : 'unusable-picture');
      return this.#out(transit ? 'skipped-in-transit' : 'skipped-unusable');
    }

    if (q) {
      const same = result.status === 'ambiguous' && result.cause === 'promotion-piece-choice' && result.candidates[0].from === q.from && result.candidates[0].to === q.to;
      if (!same) { this.#revoke('changed-while-awaiting-promotion'); return this.#out('revoked'); }
      if (evidenceOnly) return this.#out('ignored', { ignored: evidenceOnly });
      this.#skipped = 0; this.#lastUsableAt = t;
      return this.#out('awaiting-promotion-choice');
    }
    if (result.status === 'ambiguous' && result.cause !== 'promotion-piece-choice') { this.#revoke('ambiguous-change'); return this.#out('revoked'); }
    if (result.status !== 'unchanged' && this.#terminal) { this.#revoke('change-after-game-over'); return this.#out('revoked'); }
    const key = result.status === 'unchanged' ? 'unchanged' : result.status === 'move' ? `move:${result.move.uci}` : `promotion:${result.candidates[0].from}${result.candidates[0].to}`;
    // A lift that ends with the board unchanged cannot be told apart from two own pieces swapped behind it: revoke.
    if (this.#lift !== null && key === 'unchanged') { this.#revoke('lifted-piece-returned'); return this.#out('revoked'); }
    // Likewise any other definite change (a move-shaped picture, a parked piece) that ends with the board unchanged.
    if (this.#changeSeen && key === 'unchanged') { this.#revoke('changed-and-returned'); return this.#out('revoked'); }
    if (this.#status === 'verifying' && key !== 'unchanged') { this.#revoke('confirmed-position-not-seen'); return this.#out('revoked'); }
    // Round 7b: a repeated image (frozen or replayed feed) that shows a changed board cannot leave trust in place. (When not
    // ready, a repeated image is evidence only: it never counts toward the agreement that would make the tracker ready.)
    if (duplicate && key !== 'unchanged' && this.#status === 'ready') { this.#revoke('replayed-picture-changed'); return this.#out('revoked'); }
    if (evidenceOnly) return this.#out('ignored', { ignored: evidenceOnly });

    // Agreement: agreeFrames consecutive usable pictures, same key, same base FEN, each >= minFrameGapMs after the last
    // counted one; a too-soon picture is ignored entirely (no skip-cap reset, no silence refresh).
    const p = this.#pending;
    const sameRun = p && p.key === key && p.fen === this.#fen;
    if (sameRun && t - p.lastAt < this.#o.minFrameGapMs) return this.#out('too-soon');
    this.#skipped = 0; this.#lastUsableAt = t; this.#lift = null;
    if (this.#status === 'ready' && key === 'unchanged') { this.#pending = null; return this.#out('unchanged'); }
    if (sameRun) { p.count++; p.lastAt = t; } else this.#pending = { key, fen: this.#fen, count: 1, firstAt: t, lastAt: t };
    if (this.#status === 'ready') this.#set('confirming-change', 'waiting-for-agreement');
    else if (this.#status === 'confirming-change' && !sameRun) this.#revision++;
    const span = this.#pending.lastAt - this.#pending.firstAt;
    // A move also needs readyDwellMs in view (the new position must stay, not just pause on the way somewhere else).
    const settled = key === 'unchanged' || span >= (result.status === 'move'
      ? Math.max(castlingRookShaped(this.#fen, result.move) ? this.#o.castlingRookSettleMs : this.#o.minSettleMs, this.#o.readyDwellMs) : this.#o.minSettleMs);
    if (this.#pending.count < this.#o.agreeFrames || !settled) return this.#out('agreement-pending');

    this.#pending = null;
    const fenAfter = key === 'unchanged' ? this.#fen : result.status === 'move' ? result.fenAfter : result.candidates.find(c => c.promotion === 'q')?.fenAfter;
    if (fenAfter && this.#swapPossible(this.#fen, fenAfter)) { this.#revoke('pieces-may-have-swapped'); return this.#out('revoked'); }
    if (result.status === 'move' && result.move.san.startsWith('O-O') && !this.#castlingSeenSafely(this.#fen, fenAfter, result.move)) { this.#revoke('castling-not-seen-safely'); return this.#out('revoked'); }
    this.#settled();
    if (key === 'unchanged') { this.#set('ready', this.#status === 'verifying' ? this.#verifyReason : 'tracked-position-seen'); return this.#out('position-seen'); }
    if (result.status === 'move') {
      const { uci, san, from, to } = result.move;
      this.#setFen(result.fenAfter); this.#lastMove = { uci, san, from, to }; this.#movesAccepted++;
      this.#set('ready', 'move-accepted');
      return this.#out('move-accepted', { acceptedMove: { uci, san, from, to } });
    }
    const candidates = Object.fromEntries(result.candidates.map(c => [c.promotion, { uci: c.uci, san: c.san, fenAfter: c.fenAfter }]));
    if (!PROMOTION_PIECES.every(piece => candidates[piece])) { this.#revoke('ambiguous-change'); return this.#out('revoked'); }
    this.#questionCounter++;
    this.#question = { questionId: `promotion:${this.#session.sessionId}:${this.#session.epoch}:${this.#o.instanceId}:${this.#questionCounter}`, from: result.candidates[0].from, to: result.candidates[0].to,
      color: loadPosition(this.#fen).turn() === 'w' ? 'white' : 'black', fenBefore: this.#fen, askedAtMs: t, candidates, occAfter: occupancyFromFen(candidates.q.fenAfter) };
    this.#set('awaiting-promotion-choice', 'promotion-piece-unknown');
    return this.#out('promotion-question');
  }

  /** One explicit human answer to the pending promotion question: {session, questionId, piece, atMs}, all required.
   * A rejected answer changes nothing, not even the clock. An answer stamped more than maxSilenceMs ahead revokes (clock
   * unchanged). An accepted answer does NOT make the tracker ready: it moves to `verifying` and needs agreeFrames fresh
   * usable "unchanged" pictures of the new position, all captured after `atMs`. */
  answerPromotion(raw) {
    const last = this.#lastFrame?.capturedAtMs ?? 0;
    let input; try { input = plain(raw); } catch { input = null; }
    if (!exact(input, ['session', 'questionId', 'piece', 'atMs']) || typeof input.questionId !== 'string' || !int(input.atMs) || input.atMs < last ||
        !exact(input.session, ['sessionId', 'epoch'])) {
      this.#revoke('invalid-promotion-answer');
      return this.#out('revoked', { accepted: false, rejected: 'malformed-answer', error: 'answerPromotion needs exactly session, questionId, piece and atMs (safe integer, not before the last picture).' });
    }
    if (this.#tooFarAhead(input.atMs)) { this.#revoke('observation-timeout'); return this.#out('revoked', { accepted: false, rejected: 'time-jump', error: 'Answer time jumped further ahead than maxSilenceMs.' }); }
    if (!this.#session || input.session.sessionId !== this.#session.sessionId || input.session.epoch !== this.#session.epoch) return this.#out('answer-rejected', { accepted: false, rejected: 'foreign-session' });
    const q = this.#question;
    if (!q) return this.#out('answer-rejected', { accepted: false, rejected: input.questionId === this.#lastAnsweredId ? 'already-answered' : 'no-pending-question' });
    if (input.questionId !== q.questionId) return this.#out('answer-rejected', { accepted: false, rejected: 'stale-question' });
    if (!PROMOTION_PIECES.includes(input.piece)) return this.#out('answer-rejected', { accepted: false, rejected: 'invalid-piece' });
    if (this.#watchdogs(input.atMs)) return this.#out('revoked', { accepted: false, rejected: 'question-expired' });
    this.#advanceClock(input.atMs);
    const chosen = q.candidates[input.piece];
    this.#question = null; this.#lastAnsweredId = q.questionId; this.#pending = null;
    this.#setFen(chosen.fenAfter); this.#lastMove = { uci: chosen.uci, san: chosen.san, from: q.from, to: q.to, promotion: input.piece }; this.#movesAccepted++;
    // The board may have moved on while the human answered; only pictures taken after the answer can show it did not.
    this.#confirmedAt = input.atMs + 1; this.#verifyReason = 'promotion-position-seen';
    this.#set('verifying', 'verifying-after-promotion');
    return this.#out('promotion-answered', { accepted: true, answeredMove: { ...this.#lastMove } });
  }
}
