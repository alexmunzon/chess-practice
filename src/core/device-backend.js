/** In-process iPhone backend contract. No HTTP, Node APIs or remote services.
 * Native UI owns human review, frame freshness and speech permission. This
 * boundary validates chess and binds every reply to the native request identity.
 */
import {loadPosition, positionPayload, movePosition} from './position.js';
import {spokenMove} from './move-speech.js';

const record = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const exact = (v, keys) => record(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const shortId = v => typeof v === 'string' && /^[A-Za-z0-9_.:/-]{1,128}$/.test(v);
const integer = (v, min=0) => Number.isSafeInteger(v) && v >= min;
const error = (message, code='INVALID_REQUEST') => Object.assign(new Error(message), {code});
function identity(value) {
  if (!exact(value, ['sessionId','epoch','sequence','frameSha256','revision']) || !shortId(value.sessionId) ||
      !integer(value.epoch, 1) || !integer(value.sequence) || !integer(value.revision, 1) ||
      typeof value.frameSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.frameSha256)) throw error('Invalid native frame identity.');
  return {...value};
}
function request(text) {
  if (typeof text !== 'string' || text.length > 16384) throw error('Expected a bounded JSON command.');
  let data;
  try { data = JSON.parse(text); } catch { throw error('Malformed command JSON.'); }
  if (!record(data) || data.schemaVersion !== 1 || !shortId(data.requestId)) throw error('Invalid command envelope.');
  const common=['schemaVersion','requestId','kind'];
  const commands = {cancel:[],position:['fen'],move:['fen','move'],analyze:['fen','confirmation','movetimeMs','identity']};
  const fields = typeof data.kind === 'string' && Object.hasOwn(commands,data.kind) ? commands[data.kind] : null;
  if (!fields || !exact(data,[...common,...fields])) throw error('Unsupported command or extra fields.');
  if (data.kind !== 'cancel') loadPosition(data.fen);
  if (data.kind === 'move' && (!exact(data.move, Object.hasOwn(data.move ?? {},'promotion')?['from','to','promotion']:['from','to']) ||
      typeof data.move.from !== 'string' || typeof data.move.to !== 'string' || !/^[a-h][1-8]$/.test(data.move.from) || !/^[a-h][1-8]$/.test(data.move.to) ||
      (Object.hasOwn(data.move,'promotion') && !['q','r','b','n'].includes(data.move.promotion)))) throw error('Invalid move.');
  if (data.kind === 'analyze') {
    if (data.confirmation !== true) throw error('Explicit complete-state review required.', 'CONFIRMATION_REQUIRED');
    if (!integer(data.movetimeMs,50) || data.movetimeMs > 3000) throw error('Invalid bounded search time.');
    data.identity=identity(data.identity);
  }
  return data;
}

export class DeviceBackend {
  #analyzer; #job=null; #generation=0; #closed=false; #cancelling=false;
  constructor({analyzer}) {
    if (typeof analyzer !== 'function') throw new TypeError('A local engine adapter is required.');
    this.#analyzer=analyzer;
  }
  cancel() {
    const job=this.#job, wasCancelling=this.#cancelling;
    // Revoke ownership before abort listeners run. They may call back synchronously.
    this.#job=null; this.#generation++; this.#cancelling=true;
    try { job?.abort(); } finally { this.#cancelling=wasCancelling; }
  }
  close() { this.#closed=true; this.cancel(); }
  /** JSON only makes the native/WebKit boundary explicit and snapshots inputs. */
  async handle(text) {
    // An engine's abort callback cannot start an old-position replacement while
    // the caller's new-position operation is still revoking the previous job.
    if (this.#cancelling) throw error('Reentrant request during cancellation.', 'ABORTED');
    this.cancel();
    if (this.#closed) throw error('The device backend is closed.', 'CLOSED');
    const data=request(text), generation=this.#generation;
    const envelope={schemaVersion:1,requestId:data.requestId,kind:data.kind,runtime:'on-device-local'};
    if (data.kind === 'cancel') return {...envelope,cancelled:true};
    if (data.kind === 'position') return {...envelope,position:positionPayload(loadPosition(data.fen))};
    if (data.kind === 'move') {
      const chess=loadPosition(data.fen), fen=positionPayload(chess).fen, move=chess.move(data.move);
      if (move.promotion !== data.move.promotion) throw error('Unexpected promotion.');
      const checkedMove={from:move.from,to:move.to,...(move.promotion?{promotion:move.promotion}:{})};
      return {...envelope,fen,move:checkedMove,position:movePosition({fen,...checkedMove}),speechText:spokenMove(fen,checkedMove)};
    }
    const fen=positionPayload(loadPosition(data.fen)).fen;
    const controller=new AbortController();this.#job=controller;
    const current=()=>{
      if (this.#closed || controller.signal.aborted || generation !== this.#generation) throw error('Analysis superseded.', 'ABORTED');
    };
    try {
      const result=await this.#analyzer({fen,confirmation:true,movetimeMs:data.movetimeMs,requestId:data.requestId},{signal:controller.signal});
      current();
      if (!record(result) || result.requestId !== data.requestId || result.fen !== fen) throw error('Foreign engine result.', 'INVALID_RESULT');
      const position=positionPayload(loadPosition(fen));
      if (!result.bestMove) {
        if (!position.gameOver) throw error('Engine omitted a legal move.', 'INVALID_RESULT');
        current();
        return {...envelope,identity:data.identity,fen,bestMove:null,speechText:null,status:position.status};
      }
      if (position.gameOver) throw error('Engine advised a move in a terminal position.', 'INVALID_RESULT');
      const chess=loadPosition(fen);let move;
      try {
        const proposed=result.bestMove;
        move=chess.move({from:proposed.from,to:proposed.to,...(proposed.promotion?{promotion:proposed.promotion}:{})});
        if (move.promotion !== proposed.promotion) throw new Error('Unexpected promotion.');
      }
      catch { throw error('Engine returned an illegal move.', 'INVALID_RESULT'); }
      const bestMove={from:move.from,to:move.to,...(move.promotion?{promotion:move.promotion}:{}),san:move.san};
      // Generate speech from checked chess; never trust provider-supplied text.
      current();
      return {...envelope,identity:data.identity,fen,bestMove,speechText:spokenMove(fen,bestMove),status:position.status};
    } finally { if (this.#job === controller) this.#job=null; }
  }
}
