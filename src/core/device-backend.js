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
export const NODES_MIN = 1000, NODES_MAX = 2000000;
const SPARE_STATES = ['starting','ready','none'];
/** Diagnostic search facts for the reply. Never used for advice; anything malformed becomes null. */
function searchFacts(analysis) {
  const a = record(analysis) ? analysis : {}, startup = record(a.startup) ? a.startup : {};
  const count = v => Number.isSafeInteger(v) && v >= 0 ? v : null;
  const ms = v => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 600000 ? Math.round(v * 10) / 10 : null;
  const path = ['fresh','spare','fallback'].includes(startup.path) ? startup.path : null;
  return {nodes:count(a.nodes),nps:count(a.nps),elapsedMs:ms(a.elapsedMs),spareUsed:a.prewarmed === true && path === 'spare',
    startup:path,startupMs:ms(startup.waitedMs),
    fallbackReason:typeof startup.fallbackReason === 'string' && /^[a-z-]{1,40}$/.test(startup.fallbackReason) ? startup.fallbackReason : null};
}
function identity(value) {
  if (!exact(value, ['sessionId','epoch','sequence','frameSha256','revision']) || !shortId(value.sessionId) ||
      !integer(value.epoch, 1) || !integer(value.sequence) || !integer(value.revision, 1) ||
      typeof value.frameSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.frameSha256)) throw error('Invalid native frame identity.');
  return {...value};
}
function request(text, prewarming) {
  if (typeof text !== 'string' || text.length > 16384) throw error('Expected a bounded JSON command.');
  let data;
  try { data = JSON.parse(text); } catch { throw error('Malformed command JSON.'); }
  if (!record(data) || data.schemaVersion !== 1 || !shortId(data.requestId)) throw error('Invalid command envelope.');
  const common=['schemaVersion','requestId','kind'];
  // analyze carries exactly one search limit: movetimeMs or nodes. Both or neither fails the exact-key check.
  const limit = Object.hasOwn(data,'nodes') ? 'nodes' : 'movetimeMs';
  const commands = {cancel:[],position:['fen'],move:['fen','move'],analyze:['fen','confirmation',limit,'identity'],
    ...(prewarming ? {prewarm:[],cancelPrewarm:[]} : {})};
  const fields = typeof data.kind === 'string' && Object.hasOwn(commands,data.kind) ? commands[data.kind] : null;
  if (!fields || !exact(data,[...common,...fields])) throw error('Unsupported command or extra fields.');
  if (!['cancel','prewarm','cancelPrewarm'].includes(data.kind)) loadPosition(data.fen);
  if (data.kind === 'move' && (!exact(data.move, Object.hasOwn(data.move ?? {},'promotion')?['from','to','promotion']:['from','to']) ||
      typeof data.move.from !== 'string' || typeof data.move.to !== 'string' || !/^[a-h][1-8]$/.test(data.move.from) || !/^[a-h][1-8]$/.test(data.move.to) ||
      (Object.hasOwn(data.move,'promotion') && !['q','r','b','n'].includes(data.move.promotion)))) throw error('Invalid move.');
  if (data.kind === 'analyze') {
    if (data.confirmation !== true) throw error('Explicit complete-state review required.', 'CONFIRMATION_REQUIRED');
    if (Object.hasOwn(data,'nodes')) {
      if (!integer(data.nodes,NODES_MIN) || data.nodes > NODES_MAX) throw error('Invalid bounded node budget.');
    } else if (!integer(data.movetimeMs,50) || data.movetimeMs > 3000) throw error('Invalid bounded search time.');
    data.identity=identity(data.identity);
  }
  return data;
}

export class DeviceBackend {
  #analyzer; #prewarm=null; #cancelPrewarm=null; #job=null; #generation=0; #closed=false; #cancelling=false;
  /** prewarm/cancelPrewarm are optional together: prewarm() starts (or keeps) one spare engine and
   * returns 'starting', 'ready' or 'none'; it never produces a result. Without them both commands
   * are unsupported, as before. */
  constructor({analyzer, prewarm, cancelPrewarm}) {
    if (typeof analyzer !== 'function') throw new TypeError('A local engine adapter is required.');
    if ((prewarm === undefined) !== (cancelPrewarm === undefined) ||
        (prewarm !== undefined && (typeof prewarm !== 'function' || typeof cancelPrewarm !== 'function'))) {
      throw new TypeError('Prewarm and cancel-prewarm must be supplied together as functions.');
    }
    this.#analyzer=analyzer; this.#prewarm=prewarm ?? null; this.#cancelPrewarm=cancelPrewarm ?? null;
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
    const data=request(text, this.#prewarm !== null), generation=this.#generation;
    const envelope={schemaVersion:1,requestId:data.requestId,kind:data.kind,runtime:'on-device-local'};
    if (data.kind === 'cancel') return {...envelope,cancelled:true};
    // A prewarm reply carries only the spare's state: no FEN, move or text, so it can never be advice.
    if (data.kind === 'prewarm') { const spare=this.#prewarm(); return {...envelope,spare:SPARE_STATES.includes(spare) ? spare : 'none'}; }
    if (data.kind === 'cancelPrewarm') { this.#cancelPrewarm(); return {...envelope,cancelled:true}; }
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
      const limit=Object.hasOwn(data,'nodes') ? {nodes:data.nodes} : {movetimeMs:data.movetimeMs};
      const result=await this.#analyzer({fen,confirmation:true,...limit,requestId:data.requestId},{signal:controller.signal});
      current();
      if (!record(result) || result.requestId !== data.requestId || result.fen !== fen) throw error('Foreign engine result.', 'INVALID_RESULT');
      const search=searchFacts(result.analysis);
      const position=positionPayload(loadPosition(fen));
      if (!result.bestMove) {
        if (!position.gameOver) throw error('Engine omitted a legal move.', 'INVALID_RESULT');
        current();
        return {...envelope,identity:data.identity,fen,bestMove:null,speechText:null,status:position.status,search};
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
      return {...envelope,identity:data.identity,fen,bestMove,speechText:spokenMove(fen,bestMove),status:position.status,search};
    } finally { if (this.#job === controller) this.#job=null; }
  }
}
