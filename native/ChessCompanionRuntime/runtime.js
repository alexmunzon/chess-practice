// Loaded only by the native host's private chess-local://bundle resource scheme.
import {DeviceBackend} from './core/device-backend.js';
import {createPrewarmedAnalyzer} from './core/prewarmed-engine.js';
import {ReplayRuntime} from './core/replay-runtime.js';
import {OccupancyTracker, validateOccupancyFrame} from './core/occupancy-tracker.js';
import {PROMOTION_PIECES} from './core/occupancy-tracker.js';

const MAX_REPLY = 128 * 1024;
const MAX_COMMAND = 16384;
export const TRACKER_KINDS = Object.freeze(['initialize', 'observe', 'invalidate', 'snapshot']);
/** Replay-tracker traffic: any of the four tracker kinds, or anything claiming the
 * trusted-replay mode. Such text is answered only by the tracker (which rejects and
 * revokes on anything outside its contract); everything else goes to the engine
 * backend exactly as before. Engine commands never carry `mode`. */
export function isTrackerCommand(commandJSON) {
  if (typeof commandJSON !== 'string' || commandJSON.length > MAX_COMMAND) return false;
  let data;
  try { data = JSON.parse(commandJSON); } catch { return false; }
  if (data === null || typeof data !== 'object' || Array.isArray(data)) return false;
  return TRACKER_KINDS.includes(data.kind) || data.mode === 'trusted-replay';
}
/** Occupancy-tracker commands (docs/OCCUPANCY_TRACKER.md "Wiring"). They never carry `mode`. */
export const OCCUPANCY_KINDS = Object.freeze(['trackerStart', 'trackerIngest', 'trackerSnapshot', 'trackerStop', 'trackerAnswerPromotion']);
export function isOccupancyCommand(commandJSON) {
  if (typeof commandJSON !== 'string' || commandJSON.length > MAX_COMMAND) return false;
  let data;
  try { data = JSON.parse(commandJSON); } catch { return false; }
  return data !== null && typeof data === 'object' && !Array.isArray(data) && OCCUPANCY_KINDS.includes(data.kind);
}
const refusal = (message, code) => Object.assign(new Error(message), {code});
const REVIEW_KEYS = ['pieces', 'turn', 'castling', 'enPassant', 'counters'];
const plainRecord = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const exactKeys = (v, keys) => plainRecord(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const safeTime = v => Number.isSafeInteger(v) && v >= 0;
let occupancyHandlers = 0;
/** Random hex for the tracker id. A missing or failing random source, or an all-zero draw (a broken source; a real one gives
 * that with probability 2^-128), refuses: no tracker is created, so every tracker request is refused until the source works. */
function randomHex(bytes) {
  const values = new Uint8Array(bytes);
  try { globalThis.crypto.getRandomValues(values); }
  catch { throw refusal('Random source unavailable; occupancy tracker not created.', 'RANDOM_UNAVAILABLE'); }
  if (values.every(b => b === 0)) throw refusal('Random source returned all zeros; occupancy tracker not created.', 'RANDOM_UNAVAILABLE');
  return Array.from(values, b => b.toString(16).padStart(2, '0')).join('');
}
/** Accepted promotion answers remembered per page. Never evicted: when full, answers are refused and revoke (fail closed). */
const ANSWER_MEMORY = 1024;
/** The runtime's one occupancy tracker behind five request kinds. Synchronous; never touches the engine.
 * Every refusal (a thrown error) first revokes the tracker: refusing is always allowed, and a caller that sent
 * a bad request may not keep trust it had before. Replies never carry advice. The tracker object is created on
 * the first request the gate lets through, so with the setting off no tracker exists. `revoke(reason)` is the
 * native host's path for a request it gave up on (refused, timed out, cancelled): it only ever removes trust. */
export function createOccupancyHandler() {
  let created = null;
  const id = ++occupancyHandlers;
  // The instance id goes into every promotion question id. 128 random bits (crypto.getRandomValues, the same source a native
  // UUID uses) make it unique per page, so a question id from before a reload can never match one asked after it. No random
  // source: the tracker is not created and the request is refused (fails closed).
  const tracker = () => created ??= new OccupancyTracker({instanceId: `device-occupancy-${id}-${randomHex(16)}`});
  let session = null, last = null; // the session of the last start; the last reading of that session passed on
  const answered = new Map(); // questionId -> piece of every accepted promotion answer on this page (kept across stop and start)
  const revokeAndRefuse = (reason, message, code = 'INVALID_REQUEST') => { tracker().invalidate(reason); throw refusal(message, code); };
  const reply = (data, view) => ({schemaVersion: 1, requestId: data.requestId, kind: data.kind, runtime: 'on-device-local',
    mode: 'occupancy-tracking', guidanceAllowed: false, trackingReady: view.trackingReady === true, state: view});
  return {
    revoke(reason) { created?.invalidate(typeof reason === 'string' && /^[a-z-]{1,40}$/.test(reason) ? reason : 'native-revoke'); },
    handle(commandJSON) {
      let data;
      try { data = JSON.parse(commandJSON); } catch { data = null; }
      const common = ['schemaVersion', 'requestId', 'kind'];
      const fields = {trackerStart: ['session', 'fen', 'reviewed', 'atMs'], trackerIngest: ['reading'], trackerSnapshot: ['atMs'], trackerStop: [],
        trackerAnswerPromotion: ['session', 'questionId', 'piece', 'atMs']}[data?.kind];
      if (!plainRecord(data) || data.schemaVersion !== 1 || typeof data.requestId !== 'string' || !/^[A-Za-z0-9_.:/-]{1,128}$/.test(data.requestId) ||
          !fields || !exactKeys(data, [...common, ...fields])) {
        // A snapshot without its time is the one mistake that could keep stale trust alive: name it.
        if (data?.kind === 'trackerSnapshot' && plainRecord(data) && !Object.hasOwn(data, 'atMs')) revokeAndRefuse('snapshot-without-time', 'trackerSnapshot needs atMs.', 'TIME_REQUIRED');
        revokeAndRefuse('malformed-request', 'Malformed or unsupported occupancy tracker request.');
      }
      if (data.kind === 'trackerStop') return reply(data, tracker().invalidate('stopped'));
      if (data.kind === 'trackerSnapshot') {
        if (!safeTime(data.atMs)) revokeAndRefuse('invalid-time', 'trackerSnapshot needs atMs as a nonnegative safe integer.', 'TIME_REQUIRED');
        return reply(data, tracker().snapshot(data.atMs));
      }
      if (data.kind === 'trackerAnswerPromotion') {
        const s = data.session;
        // A malformed answer or a piece other than q, r, b, n is a caller bug: refused and revoked, like every other refusal.
        if (!exactKeys(s, ['sessionId', 'epoch']) || typeof s.sessionId !== 'string' || !/^[A-Za-z0-9_.:/-]{1,128}$/.test(s.sessionId) || !Number.isSafeInteger(s.epoch) || s.epoch < 1 ||
            typeof data.questionId !== 'string' || !/^[A-Za-z0-9_.:/-]{1,512}$/.test(data.questionId) || !PROMOTION_PIECES.includes(data.piece) || !safeTime(data.atMs)) {
          revokeAndRefuse('invalid-promotion-answer', 'trackerAnswerPromotion needs session, questionId, piece (q, r, b or n) and atMs.');
        }
        // A late answer has no effect: one for another session, for no open question (after a stop, a new start, a revoke or an
        // earlier answer), for another question, or stamped with any time but the capture time of the last reading passed on
        // (requirement 3: a newer reading arrived, or the stamp is not a picture time). It is answered `answer-rejected` and
        // nothing changes, as the tracker's own rejections do. While a question is open the tracker is never ready, so a
        // rejection cannot keep advice alive. `snapshot()` without a time only reads the state; it runs no rule.
        // Two different answers to one question are doubt: revoke, whether the tracker is still verifying or already ready.
        // The same answer again is a harmless repeat and falls through to the no-effect rejection below.
        if (answered.has(data.questionId) && answered.get(data.questionId) !== data.piece) {
          revokeAndRefuse('conflicting-promotion-answer', 'A different piece was already accepted for this promotion question; tracking revoked.', 'ANSWER_CONFLICT');
        }
        const view = tracker().snapshot(), q = view.pendingQuestion;
        const rejected = view.session?.sessionId !== s.sessionId || view.session?.epoch !== s.epoch ? 'foreign-session'
          : !q ? 'no-pending-question' : q.questionId !== data.questionId ? 'stale-question' : data.atMs !== last?.capturedAtMs ? 'late-answer' : null;
        if (rejected) return reply(data, {...view, event: 'answer-rejected', accepted: false, rejected});
        // The tracker moves to `verifying` (never straight to ready) and may still revoke (question expired).
        // Memory full (ANSWER_MEMORY promotions on one page): a further accepted answer could not be remembered, so a later
        // conflicting answer to it would go unseen. Refuse and revoke instead of forgetting an older one.
        if (answered.size >= ANSWER_MEMORY) revokeAndRefuse('promotion-memory-full', 'Too many promotion answers on this page; tracking revoked.', 'ANSWER_MEMORY_FULL');
        const result = tracker().answerPromotion({session: {sessionId: s.sessionId, epoch: s.epoch}, questionId: data.questionId, piece: data.piece, atMs: data.atMs});
        if (result.accepted === true) {
          answered.set(data.questionId, data.piece);
        }
        return reply(data, result);
      }
      if (data.kind === 'trackerStart') {
        if (!safeTime(data.atMs) || !exactKeys(data.reviewed, REVIEW_KEYS) || !exactKeys(data.session, ['sessionId', 'epoch'])) revokeAndRefuse('invalid-confirmation', 'trackerStart needs session, fen, all five review ticks and atMs.', 'CONFIRMATION_REQUIRED');
        let view;
        try { view = tracker().confirm({session: data.session, fen: data.fen, reviewed: data.reviewed, atMs: data.atMs}); }
        catch (error) { throw refusal(String(error.message).slice(0, 200), typeof error.code === 'string' ? error.code : 'INVALID_REQUEST'); } // confirm has revoked
        if (session?.sessionId !== data.session.sessionId || session?.epoch !== data.session.epoch) last = null;
        session = {sessionId: data.session.sessionId, epoch: data.session.epoch};
        return reply(data, view);
      }
      // trackerIngest: passed on exactly as received, never sorted, deduplicated or renumbered.
      let reading;
      try { reading = validateOccupancyFrame(data.reading); } catch (error) { revokeAndRefuse('malformed-reading', 'Malformed reading: ' + String(error.message).slice(0, 200)); }
      const id = reading.identity, current = session && id.sessionId === session.sessionId && id.epoch === session.epoch;
      // Each reading once and in order: a repeated or earlier sequence number, or a time not after the last reading's, revokes.
      if (current && last && (id.sequence <= last.sequence || reading.capturedAtMs <= last.capturedAtMs)) {
        revokeAndRefuse('reading-out-of-order', 'Reading repeated or out of order; tracking revoked.', 'OUT_OF_ORDER');
      }
      const view = tracker().ingest(data.reading);
      if (current) last = {sequence: id.sequence, capturedAtMs: reading.capturedAtMs};
      return reply(data, view);
    },
  };
}
/** One request at a time: a replay-tracker request first cancels any engine analysis, then
 * runs synchronously to completion, so the two can never overlap. Occupancy-tracker requests
 * (off unless the native host passes occupancyTracker === true) go only to `occupancy`: they
 * never cancel, wait for or reach the engine. */
export function createRequestRouter({engine, tracker, occupancy = null}) {
  if (typeof engine?.handle !== 'function' || typeof engine?.cancel !== 'function' || typeof tracker?.handle !== 'function') {
    throw new TypeError('Engine backend and replay tracker are required.');
  }
  return async function route(commandJSON, {occupancyTracker = false} = {}) {
    if (isOccupancyCommand(commandJSON)) {
      if (occupancyTracker !== true || typeof occupancy?.handle !== 'function') throw refusal('Occupancy tracker disabled.', 'TRACKER_DISABLED');
      return occupancy.handle(commandJSON);
    }
    if (!isTrackerCommand(commandJSON)) return engine.handle(commandJSON);
    engine.cancel();
    return JSON.parse(tracker.handle(commandJSON));
  };
}
/** The app's single prewarm owner (docs/PREWARMED_ENGINE.md): one AbortController at a time.
 * prewarm() asks the analyzer for its one shared spare and reports its state; it never waits and
 * never yields a result. cancel() aborts the controller, which discards a spare that no analysis
 * has taken yet. A spare already handed to an analysis is unaffected. */
export function createPrewarmControl(engine) {
  if (typeof engine?.prewarm !== 'function' || typeof engine?.state !== 'function') throw new TypeError('A prewarming analyzer is required.');
  let controller = null;
  return {
    prewarm() {
      if (!controller || controller.signal.aborted) controller = new AbortController();
      engine.prewarm({signal: controller.signal}).catch(() => {}); // never rejects; a failure only means no spare
      const spare = engine.state().spare;
      return spare === 'ready' || spare === 'starting' ? spare : 'none';
    },
    cancel() { const previous = controller; controller = null; previous?.abort(); },
  };
}
let backend, router, engine, prewarmControl, occupancy, engineURL, wasmURL, closed = false;
const workers = new Set();
function post(value) {
  const text = JSON.stringify(value);
  if (new TextEncoder().encode(text).byteLength > MAX_REPLY) throw new Error('Runtime reply exceeded limit.');
  globalThis.webkit.messageHandlers.chessRuntime.postMessage(text);
}
async function resource(path, expectedType, maxBytes) {
  const url = new URL(path, import.meta.url);
  if (url.protocol !== 'chess-local:' || url.hostname !== 'bundle') throw new Error('Local engine resource required.');
  const response = await fetch(url, {credentials:'omit', redirect:'error', cache:'no-store'});
  if (!response.ok || response.headers.get('content-type')?.split(';')[0] !== expectedType) throw new Error('Local asset type mismatch.');
  const bytes = await response.arrayBuffer();
  if (!bytes.byteLength || bytes.byteLength > maxBytes) throw new Error('Local asset size exceeds limit.');
  return bytes;
}
function createWorker() {
  if (closed || !engineURL || !wasmURL) throw new Error('Local runtime is not ready.');
  // The unchanged pinned Stockfish browser wrapper reads this hash as its WASM URL.
  const worker = new Worker(engineURL + '#' + encodeURIComponent(wasmURL));
  workers.add(worker);
  const terminate = worker.terminate.bind(worker);
  worker.terminate = () => { workers.delete(worker); terminate(); };
  return worker;
}
function cancel() { backend?.cancel(); }
/** Native host only: a tracker request it refused, timed out or cancelled. Revokes the occupancy tracker if one
 * exists (never creates one, never restores trust). Script order on the page guarantees it runs after that request. */
function revokeOccupancy(reason) { occupancy?.revoke(reason); }
function shutdown() {
  if (closed) return;
  closed = true; router = null; backend?.close();
  prewarmControl?.cancel(); engine?.dispose(); // no spare survives shutdown
  for (const worker of workers) worker.terminate();
  workers.clear();
  if (engineURL) URL.revokeObjectURL(engineURL);
  if (wasmURL) URL.revokeObjectURL(wasmURL);
  engineURL = wasmURL = null;
}
/** `occupancyTracker` is the native setting (off by default); only the boolean true enables the occupancy kinds. */
async function submit(commandJSON, transportId, occupancyTracker = false) {
  if (typeof transportId !== 'string' || !/^[A-Za-z0-9-]{1,80}$/.test(transportId)) throw new Error('Invalid transport identity.');
  try {
    if (closed || !backend || !router) throw new Error('Local runtime is not ready.');
    const result = await router(commandJSON, {occupancyTracker: occupancyTracker === true});
    post({protocolVersion:1,kind:'reply',transportId,ok:true,result});
  } catch (error) {
    post({protocolVersion:1,kind:'reply',transportId,ok:false,error:{code:typeof error.code === 'string' ? error.code : 'RUNTIME_ERROR',message:String(error.message ?? 'Local engine failed.').slice(0,512)}});
  }
}
Object.defineProperty(globalThis,'chessDeviceRuntime',{value:Object.freeze({submit,cancel,shutdown,revokeOccupancy}),writable:false,configurable:false});
globalThis.addEventListener('pagehide', shutdown);
try {
  const [script, wasm] = await Promise.all([
    resource('engine/stockfish.js','text/javascript',1024*1024),
    resource('engine/stockfish.wasm','application/wasm',128*1024*1024),
  ]);
  if (closed) throw new Error('Runtime closed during loading.');
  engineURL=URL.createObjectURL(new Blob([script],{type:'text/javascript'}));
  wasmURL=URL.createObjectURL(new Blob([wasm],{type:'application/wasm'}));
  engine=createPrewarmedAnalyzer({createWorker});
  prewarmControl=createPrewarmControl(engine);
  backend=new DeviceBackend({analyzer:engine.analyze,prewarm:prewarmControl.prewarm,cancelPrewarm:prewarmControl.cancel});
  occupancy=createOccupancyHandler();
  router=createRequestRouter({engine:backend, tracker:new ReplayRuntime(), occupancy});
  post({protocolVersion:1,kind:'ready'});
} catch (error) {
  shutdown();
  post({protocolVersion:1,kind:'fatal',error:String(error.message ?? 'Local runtime failed.').slice(0,512)});
}
