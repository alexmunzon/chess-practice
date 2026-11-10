import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { loadPosition, positionPayload } from './position.js';
const enginePath = fileURLToPath(new URL('../../node_modules/stockfish/bin/stockfish-19-single.js', import.meta.url));
export class EngineError extends Error { constructor(message, code) { super(message); this.code = code; } }
export function analyze({fen, confirmation, movetimeMs = 1000, requestId}, {signal, startupTimeoutMs = 10000, graceMs = 1500, spawnEngine = () => spawn(process.execPath, [enginePath], {stdio:['pipe','pipe','pipe']})} = {}) {
  if (confirmation !== true) return Promise.reject(new EngineError('Confirm the complete position before analysis.', 'CONFIRMATION_REQUIRED'));
  if (!Number.isInteger(movetimeMs) || movetimeMs < 50 || movetimeMs > 3000) return Promise.reject(new EngineError('movetimeMs must be an integer between 50 and 3000.', 'INVALID_TIME'));
  let chess;
  try { chess = loadPosition(fen); } catch(e) { return Promise.reject(e); }
  const position = positionPayload(chess);
  const empty = {depth:0,scoreCp:null,mate:null,pv:[],elapsedMs:0,scorePerspective:'side-to-move',bounded:true};
  const base = {requestId,fen:position.fen,status:position.status,bestMove:null,analysis:empty};
  if (signal?.aborted) return Promise.reject(new EngineError('Analysis cancelled.', 'ABORTED'));
  if (position.gameOver) return Promise.resolve(base);
  return new Promise((resolve,reject) => {
    let child, done = false, buffer = '', timer, started = Date.now(), searchStarted = false;
    let info = {...empty};
    const finish = (error, value) => {
      if (done) return;
      done = true; clearTimeout(timer); signal?.removeEventListener('abort', abort);
      // A private process per search prevents results leaking across positions. Stop then kill.
      if (child) { try { child.stdin.write('stop\nquit\n'); } catch {} child.kill('SIGKILL'); }
      error ? reject(error) : resolve(value);
    };
    const abort = () => finish(new EngineError('Analysis cancelled.', 'ABORTED'));
    const send = command => { if (!done && child.stdin.writable) child.stdin.write(command + '\n'); };
    signal?.addEventListener('abort', abort, {once:true});
    timer = setTimeout(() => finish(new EngineError('Engine startup deadline exceeded.', 'TIMEOUT')), startupTimeoutMs);
    try { child = spawnEngine(); } catch(e) { finish(e); return; }
    child.on('error', e => finish(e));
    child.stdin.on('error', e => finish(e));
    child.stderr.on('data', () => {});
    child.on('exit', () => { if (!done) finish(new EngineError('Local engine exited before a result.', 'ENGINE_EXIT')); });
    const line = text => {
      if (done) return;
      if (text === 'uciok') { send('setoption name Hash value 32'); send('isready'); }
      else if (text === 'readyok' && !searchStarted) {
        searchStarted = true; clearTimeout(timer); started = Date.now();
        timer = setTimeout(() => finish(new EngineError('Engine search deadline exceeded.', 'TIMEOUT')), movetimeMs + graceMs);
        send('ucinewgame'); send('position fen ' + position.fen); send('go movetime ' + movetimeMs);
      } else if (text.startsWith('info ') && /\bdepth \d+/.test(text)) {
        const depth = Number(text.match(/\bdepth (\d+)/)?.[1] || 0);
        const score = text.match(/\bscore (cp|mate) (-?\d+)/);
        const pv = text.match(/\bpv (.+)$/)?.[1]?.trim().split(/\s+/);
        if (score && pv && !/\b(upperbound|lowerbound)\b/.test(text)) {
          const replay = loadPosition(position.fen), legalPv = [];
          for (const uci of pv) { try { const m = replay.move({from:uci.slice(0,2),to:uci.slice(2,4),promotion:uci[4]}); legalPv.push({uci,san:m.san}); } catch { break; } }
          info = {...info,depth,scoreCp:score[1]==='cp'?Number(score[2]):null,mate:score[1]==='mate'?Number(score[2]):null,pv:legalPv};
        }
      } else if (text.startsWith('bestmove ')) {
        const uci = text.split(/\s+/)[1];
        try {
          const move = chess.move({from:uci.slice(0,2),to:uci.slice(2,4),promotion:uci[4]});
          finish(null,{...base,bestMove:{from:move.from,to:move.to,...(move.promotion?{promotion:move.promotion}:{}),uci,san:move.san},analysis:{...info,elapsedMs:Date.now()-started}});
        } catch { finish(new EngineError('Engine did not return a legal move.', 'INVALID_ENGINE_MOVE')); }
      }
    };
    child.stdout.on('data', chunk => { buffer += chunk.toString(); if (buffer.length > 1024*1024) return finish(new EngineError('Engine output exceeded limit.', 'ENGINE_OUTPUT')); let i; while ((i=buffer.indexOf('\n'))>=0) { const s=buffer.slice(0,i).trim(); buffer=buffer.slice(i+1); line(s); } });
    send('uci');
  });
}
