import { loadPosition, positionPayload } from './position.js';
import { spokenMove } from './move-speech.js';
import { WorkerEngineError } from './worker-engine.js';

/**
 * Pre-started engine workers with the analyzer contract of createWorkerAnalyzer
 * (worker-engine.js). See docs/PREWARMED_ENGINE.md, including the layers that
 * protect against a leaked warm-up result.
 *
 * - A worker serves at most ONE analysis, then is terminated. No reuse option.
 * - A spare only ever searches WARMUP_FEN, whose legal moves are all illegal in the
 *   start position and after any first White move (backstop only). After the warm-up
 *   bestmove it runs two isready/readyok cycles before it counts as ready; a bestmove
 *   in that window discards it.
 * - At hand-over the spare's listeners are removed and the analysis drains with
 *   isready/readyok (own short deadline; on silence or failure: a fresh worker with a
 *   new full start-up deadline). A bestmove before this analysis' go is ENGINE_PROTOCOL.
 * - On every path a bestmove is accepted only if, after this analysis' go, the engine
 *   sent a legal principal variation (multipv 1, any bound) and bestmove equals the
 *   first move of the last PV at the deepest depth. Otherwise ENGINE_PROTOCOL.
 * - Messages are attributed by listener identity (one closure per worker and owner,
 *   removed on hand-over/shutdown, plus liveness flags), never by message content.
 * - Prewarm failures are silent: analyze falls back to a fresh worker (old behaviour).
 */

const OUTPUT_LIMIT = 1024 * 1024;
const UCI_MOVE = /^[a-h][1-8][a-h][1-8][qrbn]?$/;
// White pieces only on ranks 3-6: none of its legal moves is legal in the start
// position or after any first White move (tests enumerate this). A backstop only.
export const WARMUP_FEN = 'r1bq1rk1/pp3ppp/2np4/4N3/1PBQ4/P1P2RK1/8/8 w - - 0 1';
export const NODES_MIN = 1000;
export const NODES_MAX = 2000000;
const HASH = 'setoption name Hash value 32';

function legalMove(chess, uci) {
  if (!UCI_MOVE.test(uci)) throw new Error('Invalid UCI move token.');
  const promotion = uci[4];
  const move = chess.move({from: uci.slice(0, 2), to: uci.slice(2, 4), ...(promotion ? {promotion} : {})});
  if (move.promotion !== promotion) throw new Error('Unexpected promotion.');
  return move;
}
const boundedInt = (value, min, max) => Number.isInteger(value) && value >= min && value <= max;
const safeNumber = (text, key) => {
  const match = text.match(new RegExp(`\\b${key} (\\d+)(?:\\s|$)`));
  if (!match) return undefined;
  const value = Number(match[1]);
  return Number.isSafeInteger(value) ? value : undefined;
};
function detach(worker, listeners) {
  for (const [type, listener] of listeners) { try { worker.removeEventListener?.(type, listener); } catch {} }
}
function kill(worker) {
  try { worker.postMessage('stop'); } catch {}
  try { worker.postMessage('quit'); } catch {}
  try { worker.terminate()?.catch?.(() => {}); } catch {}
}

export function createPrewarmedAnalyzer({
  createWorker, clock, now: nowOption, warmupNodes = 5000, maxIdleMs = 60000, prewarmTimeoutMs = 10000,
  handoverTimeoutMs = 1000
} = {}) {
  const clockFn = nowOption ?? clock ?? (() => performance.now());
  if (typeof createWorker !== 'function' || typeof clockFn !== 'function') {
    throw new TypeError('Worker factory and clock must be functions.');
  }
  if (!(warmupNodes === 0 || boundedInt(warmupNodes, NODES_MIN, 100000)) ||
      !boundedInt(maxIdleMs, 1000, 600000) || !boundedInt(prewarmTimeoutMs, 1, 60000) ||
      !boundedInt(handoverTimeoutMs, 50, 5000)) {
    throw new TypeError('Invalid prewarm options.');
  }
  const claimed = new WeakSet();
  const active = new Set();
  let spare = null, disposed = false;

  const validWorker = candidate => {
    if (!candidate || (typeof candidate !== 'object' && typeof candidate !== 'function')) {
      throw new WorkerEngineError('Worker factory did not return a Worker.', 'INVALID_WORKER');
    }
    if (claimed.has(candidate)) throw new WorkerEngineError('Each analysis requires a new private Worker.', 'WORKER_REUSED');
    claimed.add(candidate);
    if (['postMessage', 'addEventListener', 'terminate'].some(name => typeof candidate[name] !== 'function')) {
      kill(candidate);
      throw new WorkerEngineError('Worker is missing required methods.', 'INVALID_WORKER');
    }
    return candidate;
  };

  // ---------- spare lifecycle ----------
  // rec.phase: uci -> ready -> warming -> clearing1 -> clearing2 -> spare | dead | handed
  function dropSignals(rec) {
    for (const [signal, listener] of rec.signals) { try { signal.removeEventListener('abort', listener); } catch {} }
    rec.signals.clear();
  }
  function addSignal(rec, signal) {
    if (!signal || rec.signals.has(signal)) return;
    // Any caller's abort discards the spare: a cancel means some part of the app is
    // leaving review or backgrounding, and a spare is cheap to re-create.
    const listener = () => { if (!rec.owner) discard(rec); };
    rec.signals.set(signal, listener);
    signal.addEventListener('abort', listener, {once: true});
  }
  function discard(rec) {
    if (rec.phase === 'dead' || rec.phase === 'handed') return;
    rec.phase = 'dead';
    clearTimeout(rec.timer); rec.timer = undefined;
    if (spare === rec) spare = null;
    dropSignals(rec);
    if (rec.worker) { detach(rec.worker, rec.listeners); kill(rec.worker); }
    const owner = rec.owner; rec.owner = null;
    rec.resolve(false);
    owner?.(false);
  }
  function becomeReady(rec) {
    clearTimeout(rec.timer); rec.timer = undefined;
    let readyAt;
    try { readyAt = rec.now(); } catch { discard(rec); return; }
    if (readyAt >= rec.deadline) { discard(rec); return; }
    rec.readyAt = readyAt; rec.phase = 'spare';
    if (rec.owner) { handOver(rec); return; }
    // Timers may not fire while iOS suspends web content; take() re-checks age by clock.
    rec.timer = setTimeout(() => discard(rec), maxIdleMs);
    rec.resolve(true);
  }
  function handOver(rec) {
    clearTimeout(rec.timer); rec.timer = undefined;
    detach(rec.worker, rec.listeners);
    dropSignals(rec);
    rec.phase = 'handed';
    const owner = rec.owner; rec.owner = null;
    rec.resolve(true);
    owner(rec.worker);
  }
  function startSpare(signal) {
    let resolve;
    const promise = new Promise(r => { resolve = r; });
    const rec = {phase: 'uci', worker: null, listeners: [], timer: undefined, readyAt: null, owner: null,
      promise, resolve, signals: new Map(), bytes: 0, deadline: Infinity};
    let lastNow = -Infinity;
    rec.now = () => {
      const value = clockFn();
      if (!Number.isFinite(value) || value < lastNow) throw new Error('clock');
      lastNow = value; return value;
    };
    spare = rec;
    const send = command => {
      if (rec.phase === 'dead' || rec.phase === 'handed') return;
      try { rec.worker.postMessage(command); } catch { discard(rec); }
    };
    const clear = () => { rec.phase = 'clearing1'; send('stop'); send('ucinewgame'); send('isready'); };
    const line = text => {
      if (text === 'uciok' && rec.phase === 'uci') { rec.phase = 'ready'; send(HASH); send('isready'); }
      else if (text === 'readyok' && rec.phase === 'ready') {
        if (warmupNodes > 0) { rec.phase = 'warming'; send('ucinewgame'); send('position fen ' + WARMUP_FEN); send('go nodes ' + warmupNodes); }
        else clear();
      } else if (/^bestmove(?:\s|$)/.test(text)) {
        // The warm-up result is discarded unread. Any other bestmove (a duplicate,
        // or one before the warm-up search) discards the spare.
        if (rec.phase !== 'warming') { discard(rec); return; }
        clear();
      } else if (text === 'readyok' && rec.phase === 'clearing1') { rec.phase = 'clearing2'; send('isready'); }
      else if (text === 'readyok' && rec.phase === 'clearing2') becomeReady(rec);
    };
    const onMessage = event => {
      if (spare !== rec && !rec.owner) return; // late message after discard or hand-over
      if (rec.phase === 'dead' || rec.phase === 'handed') return;
      try {
        if (rec.now() >= rec.deadline && rec.phase !== 'spare') { discard(rec); return; }
        const text = event.data;
        if (typeof text !== 'string' || text.length > OUTPUT_LIMIT) { discard(rec); return; }
        rec.bytes += new TextEncoder().encode(text).byteLength;
        if (rec.bytes > OUTPUT_LIMIT) { discard(rec); return; }
        for (const part of text.split('\n')) {
          if (rec.phase === 'dead' || rec.phase === 'handed') break;
          line(part.trim());
        }
      } catch { discard(rec); }
    };
    const onFail = () => discard(rec);
    rec.listeners = [['message', onMessage], ['error', onFail], ['messageerror', onFail]];
    try {
      rec.deadline = rec.now() + prewarmTimeoutMs;
      rec.timer = setTimeout(() => discard(rec), prewarmTimeoutMs);
      rec.worker = validWorker(createWorker());
      if (rec.phase === 'dead') { kill(rec.worker); return promise; }
      for (const [type, listener] of rec.listeners) rec.worker.addEventListener(type, listener);
      addSignal(rec, signal);
      send('uci');
    } catch { discard(rec); }
    return promise;
  }
  /** Detach the spare for one analysis, or null. Old or unusable spares are discarded. */
  function take() {
    const rec = spare;
    if (!rec) return null;
    if (rec.phase === 'spare') {
      let age;
      try { age = rec.now() - rec.readyAt; } catch { discard(rec); return null; }
      if (age > maxIdleMs) { discard(rec); return null; }
    }
    spare = null;
    return rec;
  }

  /** Never rejects. False when disposed, aborted, failed, or while an analysis runs
   * (never two engines at once). Repeated calls share one spare; ANY caller's abort
   * discards it, so the app should own one controller for prewarm. */
  function prewarm({signal} = {}) {
    if (disposed || active.size > 0) return Promise.resolve(false);
    if (signal?.aborted) { if (spare) discard(spare); return Promise.resolve(false); }
    if (spare) { addSignal(spare, signal); return spare.promise; }
    return startSpare(signal);
  }

  function dispose() {
    disposed = true;
    if (spare) discard(spare);
    for (const cancel of [...active]) cancel();
  }

  function state() {
    return {disposed, spare: spare ? (spare.phase === 'spare' ? 'ready' : 'starting') : null, analyses: active.size};
  }

  // ---------- analysis ----------
  async function analyze({fen, confirmation, movetimeMs, nodes, requestId} = {},
    {signal, startupTimeoutMs = 10000, graceMs = 1500, searchTimeoutMs = 3000} = {}) {
    if (confirmation !== true) throw new WorkerEngineError('Confirm the complete position before analysis.', 'CONFIRMATION_REQUIRED');
    if (movetimeMs !== undefined && nodes !== undefined) {
      throw new WorkerEngineError('Supply either nodes or movetimeMs, not both.', 'INVALID_LIMIT');
    }
    if (nodes === undefined && movetimeMs === undefined) movetimeMs = 1000;
    if (nodes !== undefined && !boundedInt(nodes, NODES_MIN, NODES_MAX)) {
      throw new WorkerEngineError(`nodes must be an integer between ${NODES_MIN} and ${NODES_MAX}.`, 'INVALID_NODES');
    }
    if (nodes === undefined && !boundedInt(movetimeMs, 50, 3000)) {
      throw new WorkerEngineError('movetimeMs must be an integer between 50 and 3000.', 'INVALID_TIME');
    }
    if (!boundedInt(startupTimeoutMs, 1, 60000) || !boundedInt(graceMs, 0, 10000) || !boundedInt(searchTimeoutMs, 50, 30000)) {
      throw new WorkerEngineError('Invalid bounded engine deadlines.', 'INVALID_TIMEOUT');
    }
    const chess = loadPosition(fen);
    const position = positionPayload(chess);
    const limit = nodes !== undefined ? {nodes} : {movetimeMs};
    const budgetMs = nodes !== undefined ? searchTimeoutMs : movetimeMs;
    const goCommand = nodes !== undefined ? 'go nodes ' + nodes : 'go movetime ' + movetimeMs;
    const empty = {depth: 0, scoreCp: null, mate: null, pv: [], elapsedMs: 0, scorePerspective: 'side-to-move', bounded: true,
      nodes: null, nps: null, limit, prewarmed: false, startup: null};
    const base = {requestId, fen: position.fen, status: position.status, bestMove: null, speechText: null, analysis: empty};
    if (signal?.aborted) throw new WorkerEngineError('Analysis cancelled.', 'ABORTED');
    if (disposed) throw new WorkerEngineError('The analyzer is disposed.', 'CLOSED');
    if (position.gameOver) return base;

    return new Promise((resolve, reject) => {
      let worker, waiting = null, done = false, phase = 'uci', timer, deadline, started, calledAt, lastNow = -Infinity;
      let totalBytes = 0, info = {...empty}, bind = {depth: -1, move: null};
      let path = 'fresh', fallbackReason = null;
      const encoder = new TextEncoder();
      const now = () => {
        let value;
        try { value = clockFn(); } catch { throw new WorkerEngineError('Engine clock failed.', 'INVALID_CLOCK'); }
        if (!Number.isFinite(value) || value < lastNow) throw new WorkerEngineError('Engine clock must be finite and monotonic.', 'INVALID_CLOCK');
        lastNow = value;
        return value;
      };
      const listeners = () => [['message', onMessage], ['error', onError], ['messageerror', onMessageError]];
      const release = () => {
        if (waiting) { const rec = waiting; waiting = null; rec.owner = null; discard(rec); }
        if (worker) { detach(worker, listeners()); kill(worker); worker = null; }
      };
      const finish = (error, result) => {
        if (done) return;
        done = true;
        active.delete(cancelForDispose);
        clearTimeout(timer);
        signal?.removeEventListener('abort', abort);
        release();
        error ? reject(error) : resolve(result);
      };
      const abort = () => finish(new WorkerEngineError('Analysis cancelled.', 'ABORTED'));
      const cancelForDispose = () => finish(new WorkerEngineError('Analysis cancelled.', 'ABORTED'));
      const arm = ms => { clearTimeout(timer); deadline = now() + ms; timer = setTimeout(expire, ms); };
      const timeout = () => finish(new WorkerEngineError(`Engine ${phase === 'uci' || phase === 'ready' ? 'startup' : 'search'} deadline exceeded.`, 'TIMEOUT'));
      // Waiting for a warming spare, or draining an adopted spare, has its own deadline;
      // on expiry the spare is dropped and a fresh worker gets a NEW full start-up deadline.
      const expire = () => {
        if (done) return;
        if (phase === 'waiting' || phase === 'handover') fallback(phase === 'waiting' ? 'spare-not-ready' : 'handover-timeout');
        else timeout();
      };
      const send = command => {
        if (done || !worker) return;
        try { worker.postMessage(command); }
        catch { phase === 'handover' ? fallback('handover-send-failed') : finish(new WorkerEngineError('Could not send an engine command.', 'ENGINE_ERROR')); }
      };
      const onError = () => phase === 'handover' ? fallback('handover-error') : finish(new WorkerEngineError('Local engine worker failed.', 'ENGINE_ERROR'));
      const onMessageError = () => phase === 'handover' ? fallback('handover-error') : finish(new WorkerEngineError('Engine message could not be decoded.', 'ENGINE_OUTPUT'));
      const readInfo = text => {
        const nodeCount = safeNumber(text, 'nodes'), nps = safeNumber(text, 'nps');
        if (nodeCount !== undefined) info = {...info, nodes: nodeCount};
        if (nps !== undefined) info = {...info, nps};
        const depthMatch = text.match(/\bdepth (\d+)(?:\s|$)/);
        const pvText = text.match(/\bpv (.+)$/)?.[1];
        const multipv = text.match(/\bmultipv (\d+)(?:\s|$)/)?.[1];
        if (!depthMatch || !pvText || (multipv && multipv !== '1')) return;
        const depth = Number(depthMatch[1]);
        if (!Number.isSafeInteger(depth)) return;
        const tokens = pvText.trim().split(/\s+/);
        if (tokens.length > 256) return;
        const replay = loadPosition(position.fen), pv = [];
        try { for (const uci of tokens) pv.push({uci, san: legalMove(replay, uci).san}); } catch { return; }
        // Binding PV: any bound, last one at the deepest depth (the real engine's bestmove
        // matched this on 242/242 searches; it differed from the last exact PV on 8).
        if (depth >= bind.depth) bind = {depth, move: tokens[0]};
        const score = text.match(/\bscore (cp|mate) (-?\d+)(?:\s|$)/);
        if (!score || /\b(upperbound|lowerbound)\b/.test(text)) return;
        const value = Number(score[2]);
        if (!Number.isSafeInteger(value)) return;
        info = {...info, depth, scoreCp: score[1] === 'cp' ? value : null, mate: score[1] === 'mate' ? value : null, pv};
      };
      const line = text => {
        if (done) return;
        if (text === 'uciok' && phase === 'uci') {
          phase = 'ready';
          send(HASH);
          send('isready');
        } else if (text === 'readyok' && (phase === 'ready' || phase === 'handover')) {
          const readyAt = now();
          if (readyAt >= deadline) { expire(); return; }
          phase = 'starting-search';
          started = readyAt;
          info = {...info, startup: {path, fallbackReason, waitedMs: readyAt - calledAt}};
          clearTimeout(timer);
          deadline = started + budgetMs + graceMs;
          timer = setTimeout(expire, budgetMs + graceMs);
          send('ucinewgame');
          send('position fen ' + position.fen);
          if (!done) { phase = 'searching'; send(goCommand); }
        } else if (text.startsWith('info ') && phase === 'searching') {
          readInfo(text);
        } else if (/^bestmove(?:\s|$)/.test(text)) {
          if (phase !== 'searching') {
            finish(new WorkerEngineError('Engine returned a move before search.', 'ENGINE_PROTOCOL'));
            return;
          }
          const match = text.match(/^bestmove ([a-h][1-8][a-h][1-8][qrbn]?)(?: ponder ([a-h][1-8][a-h][1-8][qrbn]?))?$/);
          let move;
          try { if (!match) throw new Error(); move = legalMove(chess, match[1]); }
          catch { finish(new WorkerEngineError('Engine did not return a legal move.', 'INVALID_ENGINE_MOVE')); return; }
          if (bind.move !== match[1]) {
            finish(new WorkerEngineError('Best move is not backed by this search\'s principal variation.', 'ENGINE_PROTOCOL'));
            return;
          }
          const bestMove = {from: move.from, to: move.to, ...(move.promotion ? {promotion: move.promotion} : {}), uci: match[1], san: move.san};
          const speechText = spokenMove(position.fen, bestMove);
          const completedAt = now();
          if (completedAt >= deadline) { timeout(); return; }
          finish(null, {...base, bestMove, speechText, analysis: {...info, elapsedMs: completedAt - started}});
        }
      };
      const onMessage = event => {
        if (done) return;
        try {
          if (now() >= deadline) { expire(); return; }
          const text = event.data;
          if (typeof text !== 'string' || text.length > OUTPUT_LIMIT) {
            finish(new WorkerEngineError('Engine output exceeded limit or was not text.', 'ENGINE_OUTPUT'));
            return;
          }
          totalBytes += encoder.encode(text).byteLength;
          if (totalBytes > OUTPUT_LIMIT) {
            finish(new WorkerEngineError('Engine total output exceeded limit.', 'ENGINE_OUTPUT'));
            return;
          }
          for (const part of text.split('\n')) { line(part.trim()); if (done) break; }
        } catch (error) { finish(error instanceof WorkerEngineError ? error : new WorkerEngineError('Malformed engine output.', 'ENGINE_OUTPUT')); }
      };
      const listen = () => { for (const [type, listener] of listeners()) worker.addEventListener(type, listener); };
      // Existing behaviour: a fresh private worker, full handshake, its own full deadline.
      const fresh = () => {
        try {
          arm(startupTimeoutMs);
          phase = 'uci';
          worker = validWorker(createWorker());
          if (done) { kill(worker); worker = null; return; }
          if (signal?.aborted) { abort(); return; }
          listen();
          send('uci');
        } catch (error) { finish(error instanceof WorkerEngineError ? error : new WorkerEngineError('Could not start the engine worker.', 'ENGINE_ERROR')); }
      };
      // At most one fallback: the fresh path never falls back again.
      const fallback = reason => {
        if (done) return;
        path = 'fallback'; fallbackReason = reason;
        info = {...info, prewarmed: false};
        release();
        totalBytes = 0;
        fresh();
      };
      // A clean spare: drain with isready/readyok under a short deadline, then the same search path.
      const adopt = adopted => {
        try {
          worker = adopted;
          path = 'spare';
          info = {...info, prewarmed: true};
          phase = 'handover';
          arm(handoverTimeoutMs);
          listen();
          send('isready');
        } catch (error) { finish(error instanceof WorkerEngineError ? error : new WorkerEngineError('Engine hand-over failed.', 'ENGINE_ERROR')); }
      };
      signal?.addEventListener('abort', abort, {once: true});
      active.add(cancelForDispose);
      try { calledAt = now(); } catch (error) { finish(error); return; }
      const rec = take();
      if (!rec) { fresh(); return; }
      if (rec.phase === 'spare') { rec.owner = adopt; handOver(rec); return; }
      // Still warming: wait for it to become clean, bounded by startupTimeoutMs; if it
      // fails or is late, fall back to a fresh worker. Abort while waiting kills the spare.
      waiting = rec;
      phase = 'waiting';
      try { arm(startupTimeoutMs); } catch (error) { finish(error); return; }
      rec.owner = adopted => {
        waiting = null;
        if (done) { if (adopted) kill(adopted); return; }
        if (adopted) adopt(adopted);
        else fallback('spare-failed');
      };
    });
  }

  return {prewarm, analyze, dispose, state};
}
