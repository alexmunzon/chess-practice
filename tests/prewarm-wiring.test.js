// Wiring of the pre-started engine (src/core/prewarmed-engine.js) into the phone runtime:
// DeviceBackend's node budget and prewarm commands, runtime.js's single prewarm owner and shutdown.
// Node only: fake UCI workers, plus one real pinned-Stockfish Node worker. No WebKit or device.
import test from 'node:test';
import assert from 'node:assert/strict';
import {Worker} from 'node:worker_threads';
import {mkdtemp, rm, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {pathToFileURL} from 'node:url';
import {DeviceBackend} from '../src/core/device-backend.js';
import {createPrewarmedAnalyzer, WARMUP_FEN} from '../src/core/prewarmed-engine.js';
import {START_FEN, loadPosition} from '../src/core/position.js';
import {buildDeviceRuntime} from '../scripts/build-device-runtime.mjs';

const AFTER_E4 = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1';
const identity = {sessionId: 'prewarm-wiring', epoch: 1, sequence: 2, frameSha256: 'b'.repeat(64), revision: 1};
const command = (kind, extra = {}, requestId = 'request-' + kind) => JSON.stringify({schemaVersion: 1, requestId, kind, ...extra});
const analyze = (extra = {}, requestId = 'request-analyze') => command('analyze', {fen: START_FEN, confirmation: true, nodes: 100000, identity: {...identity}, ...extra}, requestId);
const turn = () => new Promise(resolve => setImmediate(resolve));
const settle = async (n = 10) => { for (let i = 0; i < n; i++) await turn(); };
const ANALYZE_KEYS = ['bestMove', 'fen', 'identity', 'kind', 'requestId', 'runtime', 'schemaVersion', 'search', 'speechText', 'status'];
const SEARCH_KEYS = ['elapsedMs', 'fallbackReason', 'nodes', 'nps', 'spareUsed', 'startup', 'startupMs'];

/** A fake UCI worker: answers uci/isready, and every `go` with a legal PV + bestmove for the
 * position it was given (first legal move), unless told to hold. Records commands. */
class UciWorker {
  constructor({holdSearch = false, holdWarmup = false, failStart = false} = {}) {
    Object.assign(this, {holdSearch, holdWarmup, failStart});
    this.listeners = new Map(); this.commands = []; this.terminated = 0; this.fen = null; this.held = null;
  }
  addEventListener(type, listener) { if (!this.listeners.has(type)) this.listeners.set(type, new Set()); this.listeners.get(type).add(listener); }
  removeEventListener(type, listener) { this.listeners.get(type)?.delete(listener); }
  emit(type, data) { for (const listener of [...(this.listeners.get(type) || [])]) listener({data}); }
  terminate() { this.terminated++; }
  postMessage(text) {
    this.commands.push(text);
    if (this.terminated) return;
    if (text === 'uci') queueMicrotask(() => this.failStart ? this.emit('error', new Error('no engine')) : this.emit('message', 'uciok'));
    else if (text === 'isready') queueMicrotask(() => this.emit('message', 'readyok'));
    else if (text.startsWith('position fen ')) this.fen = text.slice('position fen '.length);
    else if (text.startsWith('go ')) {
      const move = loadPosition(this.fen).moves({verbose: true})[0];
      const uci = move.from + move.to + (move.promotion ?? '');
      const reply = () => { this.emit('message', `info depth 3 score cp 10 nodes 4000 nps 200000 pv ${uci}`); this.emit('message', 'bestmove ' + uci); };
      const warmup = this.fen === WARMUP_FEN;
      if ((warmup && this.holdWarmup) || (!warmup && this.holdSearch)) this.held = reply;
      else queueMicrotask(reply);
    }
  }
  release() { const reply = this.held; this.held = null; reply?.(); }
}
function registry(options = () => ({})) {
  const workers = [];
  let maxLive = 0;
  const live = () => workers.filter(w => w.terminated === 0).length;
  const create = () => { const w = new UciWorker(options(workers.length)); workers.push(w); maxLive = Math.max(maxLive, live()); return w; };
  return {create, workers, live, get maxLive() { return maxLive; }};
}
/** The runtime.js wiring, built from the module itself (createPrewarmControl) and the real analyzer. */
async function wired(options) {
  const {createPrewarmControl} = await runtimeExports;
  const workers = registry(options);
  const engine = createPrewarmedAnalyzer({createWorker: workers.create});
  const control = createPrewarmControl(engine);
  const backend = new DeviceBackend({analyzer: engine.analyze, prewarm: control.prewarm, cancelPrewarm: control.cancel});
  return {workers, engine, control, backend};
}
// runtime.js exports are importable from the built bundle; its top-level start fails (not chess-local)
// and is irrelevant here. Built once, outside the repository.
const bundleDir = await mkdtemp(join(tmpdir(), 'prewarm-wiring-test-'));
const built = await buildDeviceRuntime(join(bundleDir, 'bundle'));
globalThis.webkit = {messageHandlers: {chessRuntime: {postMessage: () => {}}}};
if (typeof globalThis.addEventListener !== 'function') globalThis.addEventListener = () => {};
const runtimeExports = import(pathToFileURL(join(built.outputDirectory, 'runtime.js')));
test.after(() => rm(bundleDir, {recursive: true, force: true}));

test('analyze accepts exactly one bounded limit: movetimeMs 50-3000 or nodes 1,000-2,000,000', async () => {
  const seen = [];
  const backend = new DeviceBackend({analyzer: async input => { seen.push(input); return {...input, bestMove: {from: 'e2', to: 'e4'}}; }});
  for (const nodes of [1000, 100000, 2000000]) await backend.handle(analyze({nodes}));
  await backend.handle(analyze({nodes: undefined, movetimeMs: 1000}));
  assert.deepEqual(seen.map(input => Object.keys(input).sort()), [
    ...Array(3).fill(['confirmation', 'fen', 'nodes', 'requestId']), ['confirmation', 'fen', 'movetimeMs', 'requestId']]);
  assert.deepEqual(seen.map(input => input.nodes ?? input.movetimeMs), [1000, 100000, 2000000, 1000]);
  const rejected = [{nodes: 999}, {nodes: 2000001}, {nodes: 1500.5}, {nodes: '100000'}, {nodes: null}, {nodes: -1},
    {nodes: 100000, movetimeMs: 1000}, {nodes: undefined}, {nodes: undefined, movetimeMs: 3001}, {nodes: undefined, movetimeMs: 49}];
  for (const patch of rejected) await assert.rejects(backend.handle(analyze(patch)), /Invalid bounded|Unsupported command/, JSON.stringify(patch));
  assert.equal(seen.length, 4, 'no rejected request reached the engine');
  backend.close();
});

test('prewarm commands: exact keys only, unsupported without a prewarm owner, replies carry no position, move or text', async () => {
  let prewarms = 0, cancels = 0, state = 'starting';
  const backend = new DeviceBackend({analyzer: () => assert.fail('no analysis'), prewarm: () => { prewarms++; return state; }, cancelPrewarm: () => { cancels++; }});
  assert.deepEqual(await backend.handle(command('prewarm')), {schemaVersion: 1, requestId: 'request-prewarm', kind: 'prewarm', runtime: 'on-device-local', spare: 'starting'});
  state = 'ready'; assert.equal((await backend.handle(command('prewarm'))).spare, 'ready');
  state = {bestMove: 'e2e4'}; assert.equal((await backend.handle(command('prewarm'))).spare, 'none', 'anything but a known state becomes none');
  assert.deepEqual(await backend.handle(command('cancelPrewarm')), {schemaVersion: 1, requestId: 'request-cancelPrewarm', kind: 'cancelPrewarm', runtime: 'on-device-local', cancelled: true});
  for (const extra of [{fen: START_FEN}, {nodes: 100000}, {identity}, {confirmation: true}, {spare: 'ready'}]) {
    await assert.rejects(backend.handle(command('prewarm', extra)), /Unsupported command or extra fields/);
    await assert.rejects(backend.handle(command('cancelPrewarm', extra)), /Unsupported command or extra fields/);
  }
  assert.deepEqual([prewarms, cancels], [3, 1], 'rejected commands never reach the prewarm owner');
  const plain = new DeviceBackend({analyzer: () => assert.fail('no analysis')});
  for (const kind of ['prewarm', 'cancelPrewarm']) await assert.rejects(plain.handle(command(kind)), /Unsupported command/);
  assert.throws(() => new DeviceBackend({analyzer: () => {}, prewarm: () => 'none'}), /together/);
  assert.throws(() => new DeviceBackend({analyzer: () => {}, prewarm: 'yes', cancelPrewarm: () => {}}), /together/);
  backend.close(); plain.close();
});

test('analyze reply: exact keys and diagnostic search facts (malformed facts become null, never advice)', async () => {
  const facts = {nodes: 100123, nps: 350000, elapsedMs: 286.04, prewarmed: true, startup: {path: 'spare', fallbackReason: null, waitedMs: 12.37}};
  let analysis = facts;
  const backend = new DeviceBackend({analyzer: async input => ({...input, bestMove: {from: 'e2', to: 'e4'}, analysis})});
  const reply = await backend.handle(analyze());
  assert.deepEqual(Object.keys(reply).sort(), ANALYZE_KEYS);
  assert.deepEqual(reply.search, {nodes: 100123, nps: 350000, elapsedMs: 286, spareUsed: true, startup: 'spare', startupMs: 12.4, fallbackReason: null});
  analysis = {nodes: -5, nps: 1.5, elapsedMs: Infinity, prewarmed: 'yes', startup: {path: 'warm', fallbackReason: 'Bad Reason!', waitedMs: -1}};
  const bad = await backend.handle(analyze());
  assert.deepEqual(bad.search, {nodes: null, nps: null, elapsedMs: null, spareUsed: false, startup: null, startupMs: null, fallbackReason: null});
  assert.equal(bad.bestMove.san, 'e4', 'diagnostics never change the checked move');
  analysis = {prewarmed: true, startup: {path: 'fallback', fallbackReason: 'spare-failed', waitedMs: 600}};
  assert.deepEqual((await backend.handle(analyze())).search, {nodes: null, nps: null, elapsedMs: null, spareUsed: false, startup: 'fallback', startupMs: 600, fallbackReason: 'spare-failed'});
  analysis = undefined;
  assert.deepEqual(Object.keys((await backend.handle(analyze())).search).sort(), SEARCH_KEYS);
  backend.close();
});

test('runtime wiring: a ready spare serves the confirmed position with go nodes 100000; one spare, then it is gone', async () => {
  const {workers, engine, backend} = await wired();
  assert.equal((await backend.handle(command('prewarm'))).spare, 'starting');
  assert.equal((await backend.handle(command('prewarm'))).spare, 'starting', 'a repeated prewarm shares the spare');
  await settle();
  assert.equal(engine.state().spare, 'ready');
  assert.equal((await backend.handle(command('prewarm'))).spare, 'ready');
  assert.equal(workers.workers.length, 1);
  const reply = await backend.handle(analyze({fen: AFTER_E4}, 'confirmed'));
  assert.equal(reply.fen, AFTER_E4); assert.equal(reply.requestId, 'confirmed'); assert.deepEqual(reply.identity, identity);
  assert.ok(loadPosition(AFTER_E4).moves({verbose: true}).some(m => m.from === reply.bestMove.from && m.to === reply.bestMove.to), 'legal in the confirmed position');
  assert.equal(reply.search.spareUsed, true); assert.equal(reply.search.startup, 'spare'); assert.equal(reply.search.nodes, 4000);
  const spare = workers.workers[0];
  assert.ok(spare.commands.includes('go nodes 100000')); assert.ok(spare.commands.includes('position fen ' + AFTER_E4));
  assert.equal(spare.terminated, 1, 'one analysis per worker');
  assert.equal(workers.maxLive, 1); assert.equal(engine.state().spare, null);
  const second = await backend.handle(analyze({}, 'second'));
  assert.equal(second.search.spareUsed, false); assert.equal(second.search.startup, 'fresh');
  backend.close(); engine.dispose();
});

test('a warm-up result can never become advice: a stray bestmove after hand-over fails closed', async () => {
  // (a) the warm-up result re-delivered during the hand-over drain, before this analysis' go;
  // (b) a stray bestmove that is LEGAL in the confirmed position, arriving right after go, before any PV.
  for (const [when, stray] of [['isready', 'bestmove c4f7'], ['go nodes 100000', 'bestmove d2d4']]) {
    const {workers, engine, backend} = await wired();
    await backend.handle(command('prewarm')); await settle();
    const spare = workers.workers[0];
    const post = spare.postMessage.bind(spare);
    let armed = true;
    spare.postMessage = text => {
      const handover = when === 'isready' && text === 'isready' && spare.commands.filter(c => c === 'isready').length === 3;
      if (armed && (handover || (when !== 'isready' && text === when))) { armed = false; post(text); spare.emit('message', stray); return; }
      post(text);
    };
    await assert.rejects(backend.handle(analyze({}, 'after-stray')), error => error.code === 'ENGINE_PROTOCOL', when);
    assert.equal(armed, false, 'the stray was delivered');
    assert.equal(spare.terminated, 1);
    assert.equal(workers.maxLive, 1);
    backend.close(); engine.dispose();
  }
});

test('a prewarm in flight when the user confirms: the analysis waits for that spare and advises only the confirmed position', async () => {
  const {workers, engine, backend} = await wired(() => ({holdWarmup: true}));
  await backend.handle(command('prewarm')); await settle();
  assert.equal(engine.state().spare, 'starting');
  const pending = backend.handle(analyze({fen: AFTER_E4}, 'confirmed-during-warmup'));
  await settle();
  assert.equal(workers.workers.length, 1, 'no second engine while the spare warms up');
  workers.workers[0].release(); // the warm-up result arrives now, for WARMUP_FEN
  const reply = await pending;
  assert.equal(reply.fen, AFTER_E4); assert.equal(reply.requestId, 'confirmed-during-warmup');
  assert.notEqual(reply.bestMove.from + reply.bestMove.to, 'c4f7');
  assert.equal(reply.search.spareUsed, true);
  assert.equal(workers.maxLive, 1);
  backend.close(); engine.dispose();
});

test('cancelPrewarm discards the spare; a later prewarm starts one new spare; never two engines', async () => {
  const {workers, engine, backend} = await wired(() => ({holdSearch: true}));
  await backend.handle(command('prewarm')); await settle();
  await backend.handle(command('cancelPrewarm'));
  assert.equal(workers.workers[0].terminated, 1); assert.equal(engine.state().spare, null);
  assert.equal((await backend.handle(command('prewarm'))).spare, 'starting');
  await settle();
  // Analysis takes the spare and holds; a prewarm now cancels that analysis first (one engine at a time).
  const held = backend.handle(analyze({}, 'held'));
  const heldRejected = assert.rejects(held, error => error.code === 'ABORTED');
  await settle();
  assert.equal(workers.live(), 1);
  assert.equal((await backend.handle(command('prewarm'))).spare, 'starting');
  await heldRejected;
  await settle();
  assert.equal(workers.maxLive, 1, 'never two live engines');
  assert.equal(workers.workers.length, 3);
  backend.close(); engine.dispose();
  assert.equal(workers.live(), 0);
});

test('prewarm failure falls back to a fresh engine and normal advice; the failure is not an error reply', async () => {
  for (const failure of ['spare-start-error', 'factory-throws']) {
    let made = 0;
    const {createPrewarmControl} = await runtimeExports;
    const workers = [];
    const engine = createPrewarmedAnalyzer({createWorker: () => {
      made++;
      if (made === 1 && failure === 'factory-throws') throw new Error('no memory for a spare');
      const w = new UciWorker({failStart: made === 1}); workers.push(w); return w;
    }});
    const control = createPrewarmControl(engine);
    const backend = new DeviceBackend({analyzer: engine.analyze, prewarm: control.prewarm, cancelPrewarm: control.cancel});
    const prewarm = await backend.handle(command('prewarm'));
    assert.ok(['starting', 'none'].includes(prewarm.spare), failure);
    await settle();
    const reply = await backend.handle(analyze({}, 'after-failure'));
    assert.equal(reply.fen, START_FEN); assert.ok(reply.bestMove.san);
    assert.equal(reply.search.spareUsed, false); assert.equal(reply.search.startup, 'fresh', failure);
    backend.close(); engine.dispose();
  }
});

test('built runtime.js: prewarm through its own router, and shutdown leaves no engine running', async () => {
  const child = join(bundleDir, 'prewarm-runtime-child.mjs'), hooks = join(bundleDir, 'prewarm-hooks.mjs');
  const bundle = pathToFileURL(built.outputDirectory + '/').href;
  await writeFile(hooks, `
const BUNDLE=${JSON.stringify(bundle)};
export async function resolve(specifier,context,next){
 const parent=context.parentURL??'';
 if(specifier.startsWith('chess-local:')) return {url:specifier,shortCircuit:true,format:'module'};
 if(parent.startsWith('chess-local:')&&(specifier.startsWith('./')||specifier.startsWith('../'))) return {url:new URL(specifier,parent).href,shortCircuit:true,format:'module'};
 return next(specifier,context);
}
export async function load(url,context,next){
 if(!url.startsWith('chess-local:')) return next(url,context);
 const {readFile}=await import('node:fs/promises');
 return {format:'module',shortCircuit:true,source:await readFile(new URL(url.slice('chess-local://bundle/'.length),BUNDLE))};
}`);
  await writeFile(child, `
import {register} from 'node:module';
import {readFile} from 'node:fs/promises';
register(${JSON.stringify(pathToFileURL(hooks).href)});
const BUNDLE=${JSON.stringify(bundle)};
const posted=[], workers=[];
globalThis.webkit={messageHandlers:{chessRuntime:{postMessage:text=>posted.push(JSON.parse(text))}}};
globalThis.addEventListener??=()=>{};
globalThis.fetch=async url=>{
 const u=new URL(url);
 if(u.protocol!=='chess-local:'||u.hostname!=='bundle') throw new Error('non-bundle fetch '+url);
 return new Response(await readFile(new URL(u.pathname.slice(1),BUNDLE)),{headers:{'content-type':u.pathname.endsWith('.wasm')?'application/wasm':'text/javascript'}});
};
URL.createObjectURL=()=>'blob:stand-in'; URL.revokeObjectURL=()=>{};
// Stand-in page Worker: speaks just enough UCI to become a ready spare. Records lifetime.
globalThis.Worker=class{constructor(){this.l=new Map();this.terminated=false;this.commands=[];workers.push(this);}
 addEventListener(t,f){(this.l.get(t)??this.l.set(t,new Set()).get(t)).add(f);} removeEventListener(t,f){this.l.get(t)?.delete(f);}
 emit(d){for(const f of [...(this.l.get('message')??[])])f({data:d});}
 postMessage(c){this.commands.push(c);if(this.terminated)return;
  if(c==='uci')queueMicrotask(()=>this.emit('uciok'));else if(c==='isready')queueMicrotask(()=>this.emit('readyok'));
  else if(c.startsWith('go '))queueMicrotask(()=>{this.emit('info depth 1 score cp 0 pv e4f6');this.emit('bestmove e4f6');});}
 terminate(){this.terminated=true;}};
await import('chess-local://bundle/runtime.js');
const tick=()=>new Promise(r=>setImmediate(r));
await globalThis.chessDeviceRuntime.submit(JSON.stringify({schemaVersion:1,requestId:'p1',kind:'prewarm'}),'t1');
for(let i=0;i<20;i++) await tick();
await globalThis.chessDeviceRuntime.submit(JSON.stringify({schemaVersion:1,requestId:'p2',kind:'prewarm'}),'t2');
const beforeShutdown={workers:workers.length,live:workers.filter(w=>!w.terminated).length};
globalThis.chessDeviceRuntime.shutdown();
const afterShutdown={workers:workers.length,live:workers.filter(w=>!w.terminated).length,lastCommands:workers.map(w=>w.commands.slice(-2))};
await globalThis.chessDeviceRuntime.submit(JSON.stringify({schemaVersion:1,requestId:'p3',kind:'prewarm'}),'t3');
process.stdout.write(JSON.stringify({posted,beforeShutdown,afterShutdown,workersAtEnd:workers.length}));
`);
  const {stdout} = await promisify(execFile)(process.execPath, [child], {cwd: bundleDir, timeout: 30_000});
  const out = JSON.parse(stdout);
  assert.deepEqual(out.posted[0], {protocolVersion: 1, kind: 'ready'});
  assert.deepEqual(out.posted[1], {protocolVersion: 1, kind: 'reply', transportId: 't1', ok: true, result: {schemaVersion: 1, requestId: 'p1', kind: 'prewarm', runtime: 'on-device-local', spare: 'starting'}});
  assert.equal(out.posted[2].result.spare, 'ready', 'the spare finished its warm-up and drain');
  assert.deepEqual(out.beforeShutdown, {workers: 1, live: 1}, 'one spare');
  assert.deepEqual(out.afterShutdown.live, 0, 'shutdown terminated the spare');
  assert.deepEqual(out.afterShutdown.lastCommands[0], ['stop', 'quit']);
  assert.equal(out.posted[3].ok, false); assert.equal(out.workersAtEnd, 1, 'no engine after shutdown');
});

test('real pinned Stockfish (Node worker): a pre-started spare searches 100,000 nodes of the confirmed position', {timeout: 60_000}, async () => {
  const {createPrewarmControl} = await runtimeExports;
  const nodeWorker = () => {
    const native = new Worker(new URL('./fixtures/stockfish-worker.cjs', import.meta.url));
    const map = new Map();
    return {
      postMessage: text => native.postMessage(text),
      addEventListener(type, listener) { const wrapper = type === 'message' ? data => listener({data}) : listener; map.set(listener, wrapper); native.on(type, wrapper); },
      removeEventListener(type, listener) { const wrapper = map.get(listener); if (wrapper) native.off(type, wrapper); map.delete(listener); },
      terminate: () => native.terminate(),
    };
  };
  const engine = createPrewarmedAnalyzer({createWorker: nodeWorker});
  const control = createPrewarmControl(engine);
  const backend = new DeviceBackend({analyzer: engine.analyze, prewarm: control.prewarm, cancelPrewarm: control.cancel});
  await backend.handle(command('prewarm'));
  for (let i = 0; i < 300 && engine.state().spare !== 'ready'; i++) await new Promise(resolve => setTimeout(resolve, 50));
  assert.equal(engine.state().spare, 'ready');
  const reply = await backend.handle(analyze({fen: AFTER_E4}, 'real-spare'));
  assert.equal(reply.fen, AFTER_E4); assert.ok(reply.bestMove.san);
  assert.ok(loadPosition(AFTER_E4).moves({verbose: true}).some(m => m.from === reply.bestMove.from && m.to === reply.bestMove.to));
  assert.equal(reply.search.spareUsed, true); assert.equal(reply.search.startup, 'spare');
  assert.ok(reply.search.nodes >= 100000 && reply.search.nodes < 110000, 'node budget respected: ' + reply.search.nodes);
  assert.ok(reply.search.nps > 0);
  backend.close(); engine.dispose();
});
