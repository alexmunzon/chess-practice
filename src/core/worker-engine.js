import { loadPosition, positionPayload } from './position.js';
import { spokenMove } from './move-speech.js';

const OUTPUT_LIMIT = 1024 * 1024;
const UCI_MOVE = /^[a-h][1-8][a-h][1-8][qrbn]?$/;
const claimedWorkers = new WeakSet();

export class WorkerEngineError extends Error {
  constructor(message, code) { super(message); this.name = 'EngineError'; this.code = code; }
}

function legalMove(chess, uci) {
  if (!UCI_MOVE.test(uci)) throw new Error('Invalid UCI move token.');
  const promotion = uci[4];
  const move = chess.move({from: uci.slice(0, 2), to: uci.slice(2, 4), ...(promotion ? {promotion} : {})});
  // chess.js tolerates a promotion property on some non-promotion moves.
  if (move.promotion !== promotion) throw new Error('Unexpected promotion.');
  return move;
}

/**
 * Portable UCI adapter. The caller supplies a fresh Worker for each analysis,
 * configured with an explicit local engine URL. No Worker, fetch or URL is
 * created here. The pinned engine emits complete UCI lines per message; a
 * message may also contain newline-separated lines, but not partial lines.
 * Node worker tests do not establish browser, WKWebView or iPhone support.
 */
export function createWorkerAnalyzer({createWorker, clock = () => performance.now()} = {}) {
  if (typeof createWorker !== 'function' || typeof clock !== 'function') {
    throw new TypeError('Worker factory and clock must be functions.');
  }
  return async function analyze({fen, confirmation, movetimeMs = 1000, requestId} = {},
    {signal, startupTimeoutMs = 10000, graceMs = 1500} = {}) {
    if (confirmation !== true) throw new WorkerEngineError('Confirm the complete position before analysis.', 'CONFIRMATION_REQUIRED');
    if (!Number.isInteger(movetimeMs) || movetimeMs < 50 || movetimeMs > 3000) {
      throw new WorkerEngineError('movetimeMs must be an integer between 50 and 3000.', 'INVALID_TIME');
    }
    if (!Number.isInteger(startupTimeoutMs) || startupTimeoutMs < 1 || startupTimeoutMs > 60000 ||
        !Number.isInteger(graceMs) || graceMs < 0 || graceMs > 10000) {
      throw new WorkerEngineError('Invalid bounded engine deadlines.', 'INVALID_TIMEOUT');
    }
    const chess = loadPosition(fen);
    const position = positionPayload(chess);
    const empty = {depth: 0, scoreCp: null, mate: null, pv: [], elapsedMs: 0, scorePerspective: 'side-to-move', bounded: true};
    const base = {requestId, fen: position.fen, status: position.status, bestMove: null, speechText: null, analysis: empty};
    if (signal?.aborted) throw new WorkerEngineError('Analysis cancelled.', 'ABORTED');
    if (position.gameOver) return base;

    return new Promise((resolve, reject) => {
      let worker, done = false, phase = 'uci', timer, deadline, started, lastNow = -Infinity;
      let totalBytes = 0, info = {...empty};
      const encoder = new TextEncoder();
      const now = () => {
        let value;
        try { value = clock(); } catch { throw new WorkerEngineError('Engine clock failed.', 'INVALID_CLOCK'); }
        if (!Number.isFinite(value) || value < lastNow) throw new WorkerEngineError('Engine clock must be finite and monotonic.', 'INVALID_CLOCK');
        lastNow = value;
        return value;
      };
      const shutdown = () => {
        if (!worker) return;
        for (const [type, listener] of [['message', onMessage], ['error', onError], ['messageerror', onMessageError]]) {
          try { worker.removeEventListener?.(type, listener); } catch {}
        }
        try { worker.postMessage('stop'); } catch {}
        try { worker.postMessage('quit'); } catch {}
        try { worker.terminate()?.catch?.(() => {}); } catch {}
      };
      const finish = (error, result) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        signal?.removeEventListener('abort', abort);
        shutdown();
        error ? reject(error) : resolve(result);
      };
      const abort = () => finish(new WorkerEngineError('Analysis cancelled.', 'ABORTED'));
      const timeout = () => finish(new WorkerEngineError(`Engine ${phase === 'uci' || phase === 'ready' ? 'startup' : 'search'} deadline exceeded.`, 'TIMEOUT'));
      const send = command => {
        if (done) return;
        try { worker.postMessage(command); }
        catch { finish(new WorkerEngineError('Could not send an engine command.', 'ENGINE_ERROR')); }
      };
      const onError = () => finish(new WorkerEngineError('Local engine worker failed.', 'ENGINE_ERROR'));
      const onMessageError = () => finish(new WorkerEngineError('Engine message could not be decoded.', 'ENGINE_OUTPUT'));
      const readInfo = text => {
        const depthMatch = text.match(/\bdepth (\d+)(?:\s|$)/);
        const score = text.match(/\bscore (cp|mate) (-?\d+)(?:\s|$)/);
        const pvText = text.match(/\bpv (.+)$/)?.[1];
        if (!depthMatch || !score || !pvText || /\b(upperbound|lowerbound)\b/.test(text)) return;
        const multipv = text.match(/\bmultipv (\d+)(?:\s|$)/)?.[1];
        if (multipv && multipv !== '1') return;
        const depth = Number(depthMatch[1]), value = Number(score[2]);
        if (!Number.isSafeInteger(depth) || !Number.isSafeInteger(value)) return;
        const tokens = pvText.trim().split(/\s+/);
        if (tokens.length > 256) return;
        const replay = loadPosition(position.fen), pv = [];
        try {
          for (const uci of tokens) pv.push({uci, san: legalMove(replay, uci).san});
        } catch { return; }
        info = {...info, depth, scoreCp: score[1] === 'cp' ? value : null, mate: score[1] === 'mate' ? value : null, pv};
      };
      const line = text => {
        if (done) return;
        if (text === 'uciok' && phase === 'uci') {
          phase = 'ready';
          send('setoption name Hash value 32');
          send('isready');
        } else if (text === 'readyok' && phase === 'ready') {
          const readyAt = now();
          if (readyAt >= deadline) { timeout(); return; }
          phase = 'starting-search';
          started = readyAt;
          deadline = started + movetimeMs + graceMs;
          clearTimeout(timer);
          timer = setTimeout(timeout, movetimeMs + graceMs);
          send('ucinewgame');
          send('position fen ' + position.fen);
          if (!done) { phase = 'searching'; send('go movetime ' + movetimeMs); }
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
          if (now() >= deadline) { timeout(); return; }
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
      signal?.addEventListener('abort', abort, {once: true});
      try {
        deadline = now() + startupTimeoutMs;
        timer = setTimeout(timeout, startupTimeoutMs);
        const candidate = createWorker();
        if (!candidate || (typeof candidate !== 'object' && typeof candidate !== 'function')) {
          throw new WorkerEngineError('Worker factory did not return a Worker.', 'INVALID_WORKER');
        }
        if (claimedWorkers.has(candidate)) throw new WorkerEngineError('Each analysis requires a new private Worker.', 'WORKER_REUSED');
        claimedWorkers.add(candidate);
        worker = candidate;
        if (done) { shutdown(); return; }
        if (['postMessage', 'addEventListener', 'terminate'].some(name => typeof worker[name] !== 'function')) {
          throw new WorkerEngineError('Worker is missing required methods.', 'INVALID_WORKER');
        }
        if (signal?.aborted) { abort(); return; }
        worker.addEventListener('message', onMessage);
        worker.addEventListener('error', onError);
        worker.addEventListener('messageerror', onMessageError);
        send('uci');
      } catch (error) { finish(error instanceof WorkerEngineError ? error : new WorkerEngineError('Could not start the engine worker.', 'ENGINE_ERROR')); }
    });
  };
}
