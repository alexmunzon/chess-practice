// Loaded only by the native host's private chess-local://bundle resource scheme.
import {DeviceBackend} from './core/device-backend.js';
import {createPrewarmedAnalyzer} from './core/prewarmed-engine.js';
import {ReplayRuntime} from './core/replay-runtime.js';

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
/** One request at a time: a tracker request first cancels any engine analysis, then
 * runs synchronously to completion, so the two can never overlap. */
export function createRequestRouter({engine, tracker}) {
  if (typeof engine?.handle !== 'function' || typeof engine?.cancel !== 'function' || typeof tracker?.handle !== 'function') {
    throw new TypeError('Engine backend and replay tracker are required.');
  }
  return async function route(commandJSON) {
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
let backend, router, engine, prewarmControl, engineURL, wasmURL, closed = false;
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
async function submit(commandJSON, transportId) {
  if (typeof transportId !== 'string' || !/^[A-Za-z0-9-]{1,80}$/.test(transportId)) throw new Error('Invalid transport identity.');
  try {
    if (closed || !backend || !router) throw new Error('Local runtime is not ready.');
    const result = await router(commandJSON);
    post({protocolVersion:1,kind:'reply',transportId,ok:true,result});
  } catch (error) {
    post({protocolVersion:1,kind:'reply',transportId,ok:false,error:{code:typeof error.code === 'string' ? error.code : 'RUNTIME_ERROR',message:String(error.message ?? 'Local engine failed.').slice(0,512)}});
  }
}
Object.defineProperty(globalThis,'chessDeviceRuntime',{value:Object.freeze({submit,cancel,shutdown}),writable:false,configurable:false});
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
  router=createRequestRouter({engine:backend, tracker:new ReplayRuntime()});
  post({protocolVersion:1,kind:'ready'});
} catch (error) {
  shutdown();
  post({protocolVersion:1,kind:'fatal',error:String(error.message ?? 'Local runtime failed.').slice(0,512)});
}
