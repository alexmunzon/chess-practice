import test from 'node:test';
import assert from 'node:assert/strict';
import {Worker} from 'node:worker_threads';
import {createPrewarmedAnalyzer, WARMUP_FEN} from '../src/core/prewarmed-engine.js';
import {START_FEN, loadPosition} from '../src/core/position.js';

const input = {fen: START_FEN, confirmation: true, movetimeMs: 50, requestId: 'worker-test'};
const nodeInput = {fen: START_FEN, confirmation: true, nodes: 100000, requestId: 'nodes-test'};
const turn = () => new Promise(resolve => setImmediate(resolve));
const settle = async (n = 5) => { for (let i = 0; i < n; i++) await turn(); };
const WARM_GO = 'go nodes 5000';
/** A genuine search result: a PV info line from this search, then its bestmove. */
const bm = move => `info depth 1 score cp 0 nodes 20 pv ${move}\nbestmove ${move}`;

// Same mock style as tests/worker-engine.test.js, plus warm-up awareness.
class FakeWorker {
  constructor({ready = true, best, info, onCommand, warm = 'auto', warmInfo = ['info depth 9 score cp 31 nodes 999 nps 7 pv d2d4']} = {}) {
    // Default: one PV line backing the best move, as the real engine always printed (242/242 probes).
    if (info === undefined) info = best && /^[a-h][1-8][a-h][1-8]/.test(best) ? [`info depth 1 score cp 0 pv ${best.split(' ')[0]}`] : [];
    this.listeners = new Map(); this.commands = []; this.terminated = 0; this.lastPosition = null;
    this.handle = command => {
      onCommand?.(command, this);
      if (command.startsWith('position ')) this.lastPosition = command;
      if (ready && command === 'uci') queueMicrotask(() => this.emit('message', 'uciok'));
      if (ready && command === 'isready') queueMicrotask(() => this.emit('message', 'readyok'));
      if (!command.startsWith('go ')) return;
      if (this.lastPosition === 'position fen ' + WARMUP_FEN) {
        // The fake ignores the position: d2d4 simulates the worst case, a warm-up result
        // that is also legal in START_FEN (the real warm-up position makes that impossible).
        if (warm === 'auto') queueMicrotask(() => { for (const line of warmInfo) this.emit('message', line); this.emit('message', bm('d2d4')); });
        return;
      }
      if (best !== undefined) queueMicrotask(() => {
        for (const line of info) this.emit('message', line);
        this.emit('message', 'bestmove ' + best);
      });
    };
  }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(listener);
  }
  removeEventListener(type, listener) { this.listeners.get(type)?.delete(listener); }
  postMessage(command) { this.commands.push(command); this.handle(command); }
  terminate() { this.terminated++; }
  emit(type, data) { for (const listener of [...(this.listeners.get(type) || [])]) listener({data}); }
  get listenerCount() { return [...this.listeners.values()].reduce((n, s) => n + s.size, 0); }
}

/** Factory that records every worker and counts live (never-terminated) ones. */
function registry(options = () => ({best: 'e2e4'})) {
  const workers = [];
  const create = () => { const w = new FakeWorker(typeof options === 'function' ? options(workers.length) : options); workers.push(w); return w; };
  return {create, workers, live: () => workers.filter(w => w.terminated === 0).length};
}

/** Manual fake setTimeout/clearTimeout: counts pending timers and advances time on demand. */
function fakeTimers(t) {
  const realSet = globalThis.setTimeout, realClear = globalThis.clearTimeout;
  let current = 0, nextId = 1;
  const pending = new Map();
  globalThis.setTimeout = (fn, ms = 0) => { const id = {id: nextId++}; pending.set(id, {fn, at: current + ms}); return id; };
  globalThis.clearTimeout = id => { pending.delete(id); };
  t.after(() => { globalThis.setTimeout = realSet; globalThis.clearTimeout = realClear; });
  return {
    get pending() { return pending.size; },
    get now() { return current; },
    tick(ms) {
      current += ms;
      for (const [id, timer] of [...pending].sort((a, b) => a[1].at - b[1].at)) {
        if (timer.at <= current && pending.has(id)) { pending.delete(id); timer.fn(); }
      }
    },
  };
}

function nodeWorker() {
  const native = new Worker(new URL('./fixtures/stockfish-worker.cjs', import.meta.url));
  const listeners = new Map();
  return {
    postMessage: command => native.postMessage(command),
    addEventListener(type, listener) {
      const wrapper = type === 'message' ? data => listener({data}) : listener;
      listeners.set(listener, {type, wrapper}); native.on(type, wrapper);
    },
    removeEventListener(type, listener) {
      const entry = listeners.get(listener);
      if (entry) native.off(type, entry.wrapper);
      listeners.delete(listener);
    },
    terminate: () => native.terminate()
  };
}

const analyzerOf = options => createPrewarmedAnalyzer(options).analyze;

// ---------- fallback path: copy of the existing analyzer's mock tests ----------

test('fallback: handshake, full position and one search; same result shape as worker-engine', async () => {
  const worker = new FakeWorker({best: 'e2e4 ponder e7e5', info: ['info depth 12 score cp 25 nodes 4321 nps 86420 pv e2e4 e7e5 g1f3']});
  const result = await analyzerOf({createWorker: () => worker})(input);
  assert.deepEqual(worker.commands, ['uci', 'setoption name Hash value 32', 'isready', 'ucinewgame',
    'position fen ' + START_FEN, 'go movetime 50', 'stop', 'quit']);
  assert.equal(worker.terminated, 1);
  assert.deepEqual(Object.keys(result).sort(), ['analysis', 'bestMove', 'fen', 'requestId', 'speechText', 'status']);
  assert.equal(result.fen, START_FEN); assert.equal(result.requestId, input.requestId);
  assert.equal(result.bestMove.uci, 'e2e4'); assert.equal(result.bestMove.san, 'e4');
  assert.equal(result.speechText, 'pawn from e2 to e4.');
  assert.equal(result.analysis.depth, 12); assert.equal(result.analysis.scoreCp, 25);
  assert.equal(result.analysis.nodes, 4321); assert.equal(result.analysis.nps, 86420);
  assert.deepEqual(result.analysis.limit, {movetimeMs: 50}); assert.equal(result.analysis.prewarmed, false);
  assert.deepEqual(result.analysis.pv.map(move => move.san), ['e4', 'e5', 'Nf3']);
  assert.equal(result.analysis.scorePerspective, 'side-to-move'); assert.equal(result.analysis.bounded, true);
  assert.ok(result.analysis.elapsedMs >= 0);
  assert.equal(worker.listenerCount, 0);
});

test('fallback: validation precedes worker allocation (confirmation, FEN, time, nodes, limits, deadlines)', async () => {
  let allocations = 0;
  const analyze = analyzerOf({createWorker: () => { allocations++; return new FakeWorker(); }});
  await assert.rejects(analyze({...input, confirmation: false}), {code: 'CONFIRMATION_REQUIRED'});
  await assert.rejects(analyze({...input, fen: START_FEN.split(' ')[0]}), /six-field FEN/);
  for (const movetimeMs of [49, 3001, NaN, 50.5]) await assert.rejects(analyze({...input, movetimeMs}), {code: 'INVALID_TIME'});
  for (const nodes of [999, 2000001, 1e5 + 0.5, NaN, '100000', Infinity]) await assert.rejects(analyze({...nodeInput, nodes}), {code: 'INVALID_NODES'});
  await assert.rejects(analyze({...input, nodes: 100000}), {code: 'INVALID_LIMIT'});
  for (const options of [{startupTimeoutMs: Infinity}, {startupTimeoutMs: 0}, {graceMs: -1}, {graceMs: 10001}, {searchTimeoutMs: 49}, {searchTimeoutMs: 30001}]) {
    await assert.rejects(analyze(input, options), {code: 'INVALID_TIMEOUT'});
  }
  assert.equal(allocations, 0);
});

test('fallback: terminal positions return no move; pre-aborted requests never allocate', async () => {
  let allocations = 0;
  const analyze = analyzerOf({createWorker: () => { allocations++; return new FakeWorker(); }});
  const result = await analyze({...input, fen: '7k/6Q1/5K2/8/8/8/8/8 b - - 0 1'});
  assert.equal(result.bestMove, null); assert.equal(result.speechText, null);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(analyze(input, {signal: controller.signal}), {code: 'ABORTED'});
  assert.equal(allocations, 0);
});

test('fallback: abort during creation, startup and search terminates exactly once', async () => {
  for (const phase of ['creation', 'startup', 'search']) {
    const controller = new AbortController();
    const worker = new FakeWorker({ready: phase === 'search'});
    const analyze = analyzerOf({createWorker: () => { if (phase === 'creation') controller.abort(); return worker; }});
    const rejected = assert.rejects(analyze(input, {signal: controller.signal}), {code: 'ABORTED'});
    if (phase === 'search') { await turn(); assert.ok(worker.commands.includes('go movetime 50')); }
    controller.abort(); await rejected;
    assert.equal(worker.terminated, 1);
    if (phase === 'creation') assert.deepEqual(worker.commands, ['stop', 'quit']);
  }
});

test('fallback: startup and search deadlines terminate silent workers', async () => {
  for (const ready of [false, true]) {
    const worker = new FakeWorker({ready});
    await assert.rejects(analyzerOf({createWorker: () => worker})(input, {startupTimeoutMs: 30, graceMs: 5}), {code: 'TIMEOUT'});
    assert.equal(worker.terminated, 1);
  }
});

test('fallback: duplicate or early handshakes never restart or bypass startup', async () => {
  const worker = new FakeWorker({ready: false});
  const pending = analyzerOf({createWorker: () => worker})(input);
  worker.emit('message', 'readyok'); assert.deepEqual(worker.commands, ['uci']);
  worker.emit('message', 'uciok\nuciok\nreadyok\nreadyok\nuciok');
  assert.equal(worker.commands.filter(command => command === 'isready').length, 1);
  assert.equal(worker.commands.filter(command => command.startsWith('go ')).length, 1);
  worker.emit('message', bm('e2e4')); await pending;
  const early = new FakeWorker({ready: false});
  const earlyResult = analyzerOf({createWorker: () => early})(input);
  early.emit('message', bm('e2e4'));
  await assert.rejects(earlyResult, {code: 'ENGINE_PROTOCOL'});
});

test('fallback: malformed, illegal and spurious-promotion best moves are rejected', async () => {
  for (const best of ['e2e5', 'e2e4q', 'e2e4junk', '(none)', '0000', '', 'e2e4 unexpected', 'e2e4 ponder invalid']) {
    const worker = new FakeWorker({best});
    await assert.rejects(analyzerOf({createWorker: () => worker})(input), {code: 'INVALID_ENGINE_MOVE'});
    assert.equal(worker.terminated, 1);
  }
  const result = await analyzerOf({createWorker: () => new FakeWorker({best: 'a7a8n'})})({...input, fen: '7k/P7/8/8/8/8/8/K7 w - - 0 1'});
  assert.equal(result.bestMove.promotion, 'n'); assert.match(result.speechText, /promote to knight/);
});

test('fallback: only wholly legal first-variation PV and safe exact scores are retained', async () => {
  const info = [
    'info depth 4 score cp 12 pv e2e4 e7e5',
    'info depth 7 score cp 90 pv e2e4 e7e6 e4e6',
    'info depth 8 score cp 91 pv e2e4q',
    'info depth 9 score cp 92 lowerbound pv d2d4',
    'info depth 10 multipv 2 score cp 93 pv d2d4',
    'info depth 999999999999999999999 score cp 94 pv d2d4',
    'info depth 12 score cp 999999999999999999999 pv d2d4',
    'info depth 13 score cp 95 nodes 999999999999999999999 pv ' + Array(257).fill('e2e4').join(' ')
  ];
  const result = await analyzerOf({createWorker: () => new FakeWorker({best: 'd2d4', info})})(input);
  // Display keeps the last exact PV (depth 4); the binding PV may be a bound line (depth 12, d2d4).
  assert.equal(result.analysis.depth, 4); assert.equal(result.analysis.scoreCp, 12);
  assert.deepEqual(result.analysis.pv.map(move => move.uci), ['e2e4', 'e7e5']);
  assert.equal(result.analysis.nodes, null, 'unsafe node counts are ignored');
});

test('fallback: non-text, oversized and cumulative output; worker and command errors terminate', async () => {
  for (const messages of [[{}], ['x'.repeat(1024*1024+1)], ['é'.repeat(530000)], Array(1025).fill('x'.repeat(1024))]) {
    const worker = new FakeWorker({ready: false});
    const pending = analyzerOf({createWorker: () => worker})(input);
    for (const data of messages) worker.emit('message', data);
    await assert.rejects(pending, {code: 'ENGINE_OUTPUT'});
    assert.equal(worker.terminated, 1);
  }
  for (const event of ['error', 'messageerror']) {
    const worker = new FakeWorker({ready: false});
    const pending = analyzerOf({createWorker: () => worker})(input);
    worker.emit(event, undefined);
    await assert.rejects(pending, {code: event === 'error' ? 'ENGINE_ERROR' : 'ENGINE_OUTPUT'});
    assert.equal(worker.terminated, 1);
  }
  const worker = new FakeWorker({onCommand: command => { if (command === 'uci') throw new Error(); }});
  await assert.rejects(analyzerOf({createWorker: () => worker})(input), {code: 'ENGINE_ERROR'});
  assert.equal(worker.terminated, 1);
});

test('fallback: overlapping searches and late callbacks isolated; reused workers reject without killing owner', async () => {
  const first = new FakeWorker(), second = new FakeWorker();
  const queue = [first, second];
  const analyze = analyzerOf({createWorker: () => queue.shift()});
  const controller = new AbortController();
  const old = analyze({...input, requestId: 'old'}, {signal: controller.signal});
  const rejected = assert.rejects(old, {code: 'ABORTED'});
  const late = [...first.listeners.get('message')][0];
  const current = analyze({...input, requestId: 'new'});
  await turn();
  controller.abort(); await rejected;
  late({data: bm('d2d4')}); late({data: 'uciok'});
  assert.equal(second.terminated, 0);
  second.emit('message', bm('e2e4'));
  const result = await current;
  assert.equal(result.requestId, 'new'); assert.equal(result.bestMove.uci, 'e2e4');
  const shared = new FakeWorker();
  const sharedAnalyzer = analyzerOf({createWorker: () => shared});
  const owner = sharedAnalyzer(input);
  await assert.rejects(sharedAnalyzer(input), {code: 'WORKER_REUSED'});
  assert.equal(shared.terminated, 0);
  await turn(); shared.emit('message', bm('e2e4')); await owner;
});

test('fallback: monotonic clock, overdue callbacks, and deadline crossing during result processing', async () => {
  let time = 100;
  const worker = new FakeWorker();
  const pending = analyzerOf({createWorker: () => worker, clock: () => time})(input);
  await turn(); time = 125; worker.emit('message', bm('e2e4'));
  assert.equal((await pending).analysis.elapsedMs, 25);
  const overdue = new FakeWorker({ready: false});
  const late = analyzerOf({createWorker: () => overdue, clock: () => time})(input, {startupTimeoutMs: 20});
  time += 21; overdue.emit('message', 'uciok'); await assert.rejects(late, {code: 'TIMEOUT'});
  for (const clock of [() => NaN, () => { throw undefined; }]) {
    await assert.rejects(analyzerOf({createWorker: () => new FakeWorker(), clock})(input), {code: 'INVALID_CLOCK'});
  }
  let completing = false, reads = 0;
  const w2 = new FakeWorker();
  const p2 = analyzerOf({createWorker: () => w2, clock: () => completing ? (++reads === 1 ? 49 : 51) : 0})(input, {graceMs: 0});
  await turn(); completing = true; w2.emit('message', bm('e2e4'));
  await assert.rejects(p2, {code: 'TIMEOUT'}); assert.equal(w2.terminated, 1);
  let r3 = 0;
  const w3 = new FakeWorker({ready: false});
  const p3 = analyzerOf({createWorker: () => w3, clock: () => ++r3 <= 2 ? 0 : 11})(input, {startupTimeoutMs: 10});
  w3.emit('message', 'uciok\nreadyok');
  await assert.rejects(p3, {code: 'TIMEOUT'});
  assert.ok(!w3.commands.some(command => command === 'ucinewgame' || command.startsWith('go ')));
});

// ---------- node limit ----------

test('nodes limit sends go nodes, reports nodes/depth/nps, and the wall-clock deadline fails closed', async () => {
  const worker = new FakeWorker({best: 'e2e4', info: ['info depth 15 seldepth 20 score cp 30 nodes 100012 nps 350000 time 286 pv e2e4 e7e5']});
  const result = await analyzerOf({createWorker: () => worker})(nodeInput);
  assert.ok(worker.commands.includes('go nodes 100000'));
  assert.ok(!worker.commands.some(c => c.startsWith('go movetime')));
  assert.deepEqual(result.analysis.limit, {nodes: 100000});
  assert.equal(result.analysis.nodes, 100012); assert.equal(result.analysis.nps, 350000); assert.equal(result.analysis.depth, 15);
  // Neither limit: the old default.
  const def = new FakeWorker({best: 'e2e4'});
  await analyzerOf({createWorker: () => def})({fen: START_FEN, confirmation: true, requestId: 'd'});
  assert.ok(def.commands.includes('go movetime 1000'));
  // Engine never answers a nodes search: TIMEOUT, no advice, worker terminated.
  const silent = new FakeWorker();
  await assert.rejects(analyzerOf({createWorker: () => silent})(nodeInput, {searchTimeoutMs: 50, graceMs: 0}), {code: 'TIMEOUT'});
  assert.equal(silent.terminated, 1);
  // Clock-based: bestmove arriving after searchTimeoutMs + graceMs is refused.
  let time = 0;
  const slow = new FakeWorker();
  const pending = analyzerOf({createWorker: () => slow, clock: () => time})(nodeInput, {searchTimeoutMs: 100, graceMs: 0});
  await turn(); time = 101; slow.emit('message', bm('e2e4'));
  await assert.rejects(pending, {code: 'TIMEOUT'});
});

// ---------- prewarm lifecycle and safety properties ----------

test('prewarm: spare is ready only after warm-up bestmove is discarded, ucinewgame sent and readyok drained', async () => {
  const reg = registry(() => ({best: 'e2e4', warm: 'manual'}));
  const engine = createPrewarmedAnalyzer({createWorker: reg.create});
  let ready = null;
  engine.prewarm().then(v => { ready = v; });
  await settle();
  const spare = reg.workers[0];
  assert.deepEqual(spare.commands, ['uci', 'setoption name Hash value 32', 'isready', 'ucinewgame', 'position fen ' + WARMUP_FEN, WARM_GO]);
  assert.equal(engine.state().spare, 'starting'); assert.equal(ready, null);
  spare.emit('message', 'info depth 5 score cp 10 nodes 4000 nps 1 pv d2d4');
  spare.emit('message', bm('d2d4'));
  await settle();
  assert.deepEqual(spare.commands.slice(6), ['stop', 'ucinewgame', 'isready', 'isready'], 'two drain cycles');
  assert.equal(ready, true); assert.equal(engine.state().spare, 'ready');
  const result = await engine.analyze({...nodeInput, requestId: 'after-ready'});
  assert.equal(reg.workers.length, 1, 'the spare was used; no fresh worker');
  assert.deepEqual(spare.commands.slice(10), ['isready', 'ucinewgame', 'position fen ' + START_FEN, 'go nodes 100000', 'stop', 'quit']);
  assert.equal(result.analysis.prewarmed, true); assert.equal(result.bestMove.uci, 'e2e4');
  assert.equal(result.analysis.nodes, null, 'warm-up info never reaches the result');
  assert.equal(spare.terminated, 1); assert.equal(spare.listenerCount, 0);
  assert.equal(engine.state().spare, null);
});

test('a: warm-up output never resolves analyze, whether analyze comes before or after the spare is clean', async () => {
  // Ordering 1: analyze while warm-up is running. It waits for the clean spare.
  {
    const reg = registry(() => ({best: 'e2e4', warm: 'manual'}));
    const engine = createPrewarmedAnalyzer({createWorker: reg.create});
    engine.prewarm(); await settle();
    let settled = false;
    const pending = engine.analyze({...nodeInput, requestId: 'during-warmup'}).finally(() => { settled = true; });
    await settle();
    const spare = reg.workers[0];
    spare.emit('message', 'info depth 9 score cp 31 nodes 999 nps 7 pv d2d4');
    spare.emit('message', bm('d2d4'));
    await settle();
    assert.equal(reg.workers.length, 1);
    const result = await pending;
    assert.ok(settled);
    assert.equal(result.bestMove.uci, 'e2e4', 'the warm-up d2d4 was not used');
    assert.equal(result.requestId, 'during-warmup'); assert.equal(result.fen, START_FEN);
    assert.equal(result.analysis.prewarmed, true); assert.equal(result.analysis.nodes, null);
    const goes = spare.commands.filter(c => c.startsWith('go '));
    assert.deepEqual(goes, [WARM_GO, 'go nodes 100000']);
  }
  // Ordering 2: analyze after the spare is clean; a stray bestmove before the analysis' own
  // search (impossible for a real UCI engine, simulated here) fails closed.
  {
    const reg = registry(() => ({ready: true, warm: 'auto'}));
    const engine = createPrewarmedAnalyzer({createWorker: reg.create});
    assert.equal(await engine.prewarm(), true);
    const spare = reg.workers[0];
    spare.handle = command => { spare.lastPosition = command; }; // goes silent after hand-over
    const pending = engine.analyze(nodeInput);
    spare.emit('message', bm('d2d4'));
    await assert.rejects(pending, {code: 'ENGINE_PROTOCOL'});
    assert.equal(spare.terminated, 1);
  }
});

test('b: a worker serves one analysis; late output of analysis N cannot reach analysis N+1', async () => {
  const reg = registry(() => ({best: undefined}));
  const engine = createPrewarmedAnalyzer({createWorker: reg.create});
  await engine.prewarm();
  const first = engine.analyze({...nodeInput, requestId: 'n'});
  await settle();
  const w1 = reg.workers[0];
  const lateListener = [...w1.listeners.get('message')].find(Boolean);
  w1.emit('message', bm('e2e4'));
  assert.equal((await first).requestId, 'n');
  assert.equal(w1.terminated, 1);
  await engine.prewarm();
  const w2 = reg.workers[1];
  assert.notEqual(w1, w2);
  const second = engine.analyze({...nodeInput, fen: 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1', requestId: 'n+1'});
  await settle();
  lateListener({data: bm('e2e4')}); // illegal for black; would be rejected if it ever reached n+1
  w1.emit('message', bm('e2e4'));
  w2.emit('message', bm('e7e5'));
  const result = await second;
  assert.equal(result.requestId, 'n+1'); assert.equal(result.bestMove.uci, 'e7e5');
  // Without prewarm the next analysis gets a fresh worker, never w2 again.
  const third = engine.analyze({...nodeInput, requestId: 'n+2'});
  await settle();
  assert.equal(reg.workers.length, 3); reg.workers[2].emit('message', bm('d2d4'));
  assert.equal((await third).analysis.prewarmed, false);
  assert.equal(reg.live(), 0);
});

test('c: late messages from discarded, disposed or replaced spares are ignored', async () => {
  const reg = registry(() => ({best: 'e2e4', warm: 'manual'}));
  const engine = createPrewarmedAnalyzer({createWorker: reg.create});
  const outcome = engine.prewarm(); await settle();
  const old = reg.workers[0];
  const oldListener = [...old.listeners.get('message')][0];
  engine.dispose();
  assert.equal(await outcome, false); assert.equal(old.terminated, 1);
  for (const data of ['bestmove d2d4', 'readyok', 'uciok', {}]) oldListener({data});
  assert.deepEqual(engine.state(), {disposed: true, spare: null, analyses: 0});
  assert.equal(await engine.prewarm(), false);
  await assert.rejects(engine.analyze(nodeInput), {code: 'CLOSED'});
  assert.equal(reg.workers.length, 1);

  // A spare replaced after idle expiry: its late messages cannot ready or resolve anything.
  let time = 0;
  const reg2 = registry(() => ({best: 'e2e4'}));
  const e2 = createPrewarmedAnalyzer({createWorker: reg2.create, clock: () => time, maxIdleMs: 1000});
  await e2.prewarm();
  const stale = reg2.workers[0];
  const staleListener = [...stale.listeners.get('message')][0];
  time = 5000;
  const result = e2.analyze(nodeInput);
  staleListener({data: 'readyok'}); staleListener({data: bm('d2d4')});
  assert.equal((await result).bestMove.uci, 'e2e4');
  assert.equal(stale.terminated, 1); assert.equal(reg2.workers.length, 2);
});

test('d: cancel during prewarm, during search, between them, and dispose leave no worker and no timer', async t => {
  const timers = fakeTimers(t);
  const cases = {
    'abort prewarm during startup': async (engine, reg) => {
      const c = new AbortController(); const p = engine.prewarm({signal: c.signal}); await settle();
      c.abort(); assert.equal(await p, false);
    },
    'abort prewarm when spare is ready (between)': async (engine, reg) => {
      reg.manualWarm = false;
      const c = new AbortController(); assert.equal(await engine.prewarm({signal: c.signal}), true);
      assert.equal(timers.pending, 1, 'only the idle timer'); c.abort();
    },
    'abort analyze waiting on a warming spare': async (engine, reg) => {
      engine.prewarm(); await settle();
      const c = new AbortController(); const p = engine.analyze(nodeInput, {signal: c.signal}); await settle();
      c.abort(); await assert.rejects(p, {code: 'ABORTED'});
    },
    'abort analyze during search on the spare': async (engine, reg) => {
      reg.manualWarm = false;
      await engine.prewarm();
      const c = new AbortController(); const p = engine.analyze(nodeInput, {signal: c.signal}); await settle();
      assert.ok(reg.workers[0].commands.includes('go nodes 100000'));
      c.abort(); await assert.rejects(p, {code: 'ABORTED'});
    },
    'abort analyze during fresh search while a new spare warms': async (engine, reg) => {
      const c = new AbortController(); const p = engine.analyze(nodeInput, {signal: c.signal}); await settle();
      assert.equal(await engine.prewarm(), false, 'no second engine during an analysis');
      c.abort(); await assert.rejects(p, {code: 'ABORTED'}); engine.dispose();
    },
    'dispose during prewarm': async engine => { const p = engine.prewarm(); await settle(); engine.dispose(); assert.equal(await p, false); },
    'dispose with ready spare': async (engine, reg) => { reg.manualWarm = false; await engine.prewarm(); engine.dispose(); },
    'dispose during analysis waiting on spare': async engine => {
      engine.prewarm(); await settle(); const p = engine.analyze(nodeInput); await settle();
      engine.dispose(); await assert.rejects(p, {code: 'ABORTED'});
    },
    'dispose during search': async (engine, reg) => {
      reg.manualWarm = false; await engine.prewarm(); const p = engine.analyze(nodeInput); await settle();
      engine.dispose(); await assert.rejects(p, {code: 'ABORTED'});
    },
  };
  for (const [name, run] of Object.entries(cases)) {
    const reg = registry(() => ({best: undefined, warm: reg.manualWarm ? 'manual' : 'auto'}));
    reg.manualWarm = true;
    const engine = createPrewarmedAnalyzer({createWorker: reg.create, clock: () => timers.now});
    await run(engine, reg);
    await settle();
    assert.ok(reg.workers.length >= 1, name);
    assert.equal(reg.live(), 0, name + ': live workers');
    assert.ok(reg.workers.every(w => w.listenerCount === 0), name + ': listeners');
    assert.equal(timers.pending, 0, name + ': pending timers');
    assert.equal(engine.state().spare, null, name);
    assert.equal(engine.state().analyses, 0, name);
  }
});

test('e: spare failures are silent and analyze falls back to a fresh worker', async t => {
  const timers = fakeTimers(t);
  const failures = {
    'factory throws': () => { throw new Error('no worker'); },
    'factory returns junk': () => 42,
    'worker error event': () => { const w = new FakeWorker({ready: false}); queueMicrotask(() => w.emit('error')); return w; },
    'messageerror': () => { const w = new FakeWorker({ready: false}); queueMicrotask(() => w.emit('messageerror')); return w; },
    'postMessage throws': () => new FakeWorker({onCommand: () => { throw new Error('closed'); }}),
    'early bestmove': () => { const w = new FakeWorker({ready: false}); queueMicrotask(() => w.emit('message', bm('e2e4'))); return w; },
    'start-up deadline': () => new FakeWorker({ready: false}),
  };
  for (const [name, spareFactory] of Object.entries(failures)) {
    let calls = 0; const created = [];
    const engine = createPrewarmedAnalyzer({clock: () => timers.now, createWorker: () => {
      calls++;
      if (calls === 1) { const w = spareFactory(); created.push(w); return w; }
      const w = new FakeWorker({best: 'e2e4'}); created.push(w); return w;
    }});
    const outcome = engine.prewarm();
    await settle();
    if (name === 'start-up deadline') timers.tick(10000);
    assert.equal(await outcome, false, name);
    assert.equal(engine.state().spare, null, name);
    const result = await engine.analyze(nodeInput);
    assert.equal(result.bestMove.uci, 'e2e4', name); assert.equal(result.analysis.prewarmed, false, name);
    assert.equal(calls, 2, name);
    assert.ok(created.every(w => typeof w !== 'object' || w.terminated >= 1), name + ': all terminated');
    assert.equal(timers.pending, 0, name);
  }
  // Spare fails while an analysis is waiting for it: fresh fallback, no error surfaces.
  const waitReg = registry(i => i === 0 ? {ready: false} : {best: 'e2e4'});
  const engine = createPrewarmedAnalyzer({createWorker: waitReg.create, clock: () => timers.now});
  engine.prewarm(); await settle();
  const pending = engine.analyze(nodeInput); await settle();
  waitReg.workers[0].emit('error');
  const result = await pending;
  assert.equal(result.analysis.prewarmed, false); assert.equal(waitReg.workers.length, 2); assert.equal(waitReg.live(), 0);
  assert.equal(timers.pending, 0);
});

test('f: a spare older than maxIdleMs is replaced, by clock check (suspended timers) and by idle timer', async t => {
  const timers = fakeTimers(t);
  let clock = 0;
  const reg = registry(() => ({best: 'e2e4'}));
  const engine = createPrewarmedAnalyzer({createWorker: reg.create, clock: () => clock, maxIdleMs: 60000});
  await engine.prewarm();
  clock = 60001; // timers did not run (as when iOS suspends web content)
  const result = await engine.analyze(nodeInput);
  assert.equal(result.analysis.prewarmed, false);
  assert.equal(reg.workers[0].terminated, 1); assert.equal(reg.workers.length, 2);
  await engine.prewarm();
  assert.equal(engine.state().spare, 'ready');
  timers.tick(60000);
  assert.equal(engine.state().spare, null); assert.equal(reg.workers[2].terminated, 1);
  assert.equal(timers.pending, 0);
  assert.throws(() => createPrewarmedAnalyzer({createWorker: reg.create, maxIdleMs: 999}), TypeError);
  assert.throws(() => createPrewarmedAnalyzer({createWorker: reg.create, warmupNodes: 1}), TypeError);
});

test('g: at most one spare; repeated prewarm calls are idempotent', async () => {
  const reg = registry(() => ({best: 'e2e4'}));
  const engine = createPrewarmedAnalyzer({createWorker: reg.create});
  const promises = [engine.prewarm(), engine.prewarm(), engine.prewarm()];
  assert.equal(new Set(promises).size, 1);
  await Promise.all(promises);
  await engine.prewarm(); await engine.prewarm();
  assert.equal(reg.workers.length, 1);
  engine.dispose(); assert.equal(reg.live(), 0);
});

test('h: results bind to the call that asked; overlapping spare and fresh analyses never cross', async () => {
  const reg = registry(() => ({best: undefined}));
  const engine = createPrewarmedAnalyzer({createWorker: reg.create});
  await engine.prewarm();
  const black = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1';
  const a = engine.analyze({...nodeInput, requestId: 'A'});
  const b = engine.analyze({...nodeInput, fen: black, requestId: 'B'});
  await settle();
  const [wa, wb] = reg.workers;
  assert.ok(wa.commands.includes('position fen ' + START_FEN)); assert.ok(wb.commands.includes('position fen ' + black));
  wb.emit('message', bm('e7e5'));
  wa.emit('message', bm('d2d4'));
  const [ra, rb] = await Promise.all([a, b]);
  assert.deepEqual([ra.requestId, ra.fen, ra.bestMove.uci, ra.analysis.prewarmed], ['A', START_FEN, 'd2d4', true]);
  assert.deepEqual([rb.requestId, rb.fen, rb.bestMove.uci, rb.analysis.prewarmed], ['B', black, 'e7e5', false]);
});

// ---------- round 2: reviewer attacks (each failed against the round-1 module) ----------

test('S1 attack: a late duplicate warm-up bestmove after this search\'s go, without a PV, is not advice', async () => {
  let w; const engine = createPrewarmedAnalyzer({createWorker: () => (w = new FakeWorker({onCommand: (c, x) => {
    if (c === 'go nodes 100000') queueMicrotask(() => x.emit('message', 'bestmove d2d4'));
  }}))});
  assert.equal(await engine.prewarm(), true);
  await assert.rejects(engine.analyze({...nodeInput, requestId: 'R1'}), {code: 'ENGINE_PROTOCOL'});
  assert.equal(w.terminated, 1);
});

test('S1: bestmove must equal the first move of the last PV at the deepest depth, on both paths', async () => {
  for (const prewarm of [false, true]) {
    const cases = [
      [['info depth 10 score cp 5 pv e2e4 e7e5'], 'd2d4', 'ENGINE_PROTOCOL'],   // differs from PV
      [['info depth 10 score cp 5 pv d2d4', 'info depth 9 score cp 5 pv e2e4'], 'e2e4', 'ENGINE_PROTOCOL'], // shallower
      [['info depth 10 multipv 2 score cp 5 pv d2d4'], 'd2d4', 'ENGINE_PROTOCOL'], // not the main line
      [['info depth 10 score cp 5 pv d2d4 d7d4'], 'd2d4', 'ENGINE_PROTOCOL'],    // illegal PV
      [['info depth 1 currmove e2e4 currmovenumber 1'], 'e2e4', 'ENGINE_PROTOCOL'], // no PV at all
      [['info depth 10 score cp 5 pv d2d4', 'info depth 10 score cp 9 upperbound pv e2e4'], 'e2e4', null], // last at deepest, any bound
      [['info depth 3 seldepth 5 multipv 1 score cp 19 upperbound nodes 1005 pv e2e4'], 'e2e4', null], // real 1000-node shape
    ];
    for (const [info, best, code] of cases) {
      const reg = registry(() => ({best, info}));
      const engine = createPrewarmedAnalyzer({createWorker: reg.create});
      if (prewarm) assert.equal(await engine.prewarm(), true);
      const pending = engine.analyze(nodeInput);
      if (code) await assert.rejects(pending, {code}, JSON.stringify(info));
      else assert.equal((await pending).bestMove.uci, best);
      assert.equal(reg.live(), 0);
    }
  }
});

test('S1: game-over positions never reach the engine, so bestmove (none) cannot occur; (none) is rejected anyway', async () => {
  let made = 0;
  const engine = createPrewarmedAnalyzer({createWorker: () => { made++; return new FakeWorker({best: '(none)'}); }});
  for (const fen of ['7k/6Q1/5K2/8/8/8/8/8 b - - 0 1', '7k/8/8/8/8/8/5q2/7K w - - 0 1']) {
    const result = await engine.analyze({...nodeInput, fen});
    assert.equal(result.bestMove, null);
  }
  assert.equal(made, 0);
  await assert.rejects(engine.analyze(nodeInput), {code: 'INVALID_ENGINE_MOVE'});
});

test('S1b: no legal warm-up move is legal in the start position or after any first White move', () => {
  const warm = loadPosition(WARMUP_FEN);
  const moves = warm.moves({verbose: true}).map(m => m.from + m.to + (m.promotion || ''));
  assert.ok(moves.length > 20, 'a real middlegame warm-up');
  const targets = [START_FEN];
  for (const m of loadPosition(START_FEN).moves({verbose: true})) { const c = loadPosition(START_FEN); c.move(m); targets.push(c.fen()); }
  assert.equal(targets.length, 21);
  for (const fen of targets) for (const uci of moves) {
    const c = loadPosition(fen);
    assert.throws(() => c.move({from: uci.slice(0, 2), to: uci.slice(2, 4), ...(uci[4] ? {promotion: uci[4]} : {})}), `${uci} in ${fen}`);
  }
});

test('S1c: a duplicate warm-up bestmove during either drain cycle discards the spare', async () => {
  for (const after of [0, 1]) {
    let readyoks = 0;
    const reg = registry(() => ({best: 'e2e4', onCommand: (c, x) => {
      if (c === 'isready' && x.commands.includes('stop') && readyoks++ === after) queueMicrotask(() => x.emit('message', 'bestmove d2d4'));
    }}));
    const engine = createPrewarmedAnalyzer({createWorker: reg.create});
    assert.equal(await engine.prewarm(), false, 'cycle ' + after);
    assert.equal(reg.workers[0].terminated, 1);
    const result = await engine.analyze(nodeInput);
    assert.equal(result.analysis.prewarmed, false);
  }
});

test('S3i attack: a spare that went silent while idle falls back to a fresh worker with a new full deadline', async () => {
  const made = [];
  const engine = createPrewarmedAnalyzer({handoverTimeoutMs: 50, createWorker: () => {
    const w = new FakeWorker({best: 'e2e4'});
    made.push(w); return w;
  }});
  assert.equal(await engine.prewarm(), true);
  made[0].handle = () => {}; // went silent while idle (hung, or reclaimed by iOS)
  const result = await engine.analyze(nodeInput, {startupTimeoutMs: 200});
  assert.equal(result.bestMove.uci, 'e2e4'); assert.equal(made.length, 2);
  assert.equal(result.analysis.prewarmed, false);
  assert.equal(result.analysis.startup.path, 'fallback'); assert.equal(result.analysis.startup.fallbackReason, 'handover-timeout');
  assert.equal(made[0].terminated, 1);
});

test('S3i: an adopted spare that errors during the drain falls back; normal hand-over reports its wait', async () => {
  const reg = registry(i => i === 0 ? {best: 'e2e4', onCommand: (c, x) => { if (x.commands.filter(k => k === 'isready').length === 4) { x.handle = () => {}; queueMicrotask(() => x.emit('error')); } }} : {best: 'e2e4'});
  const engine = createPrewarmedAnalyzer({createWorker: reg.create});
  assert.equal(await engine.prewarm(), true);
  const result = await engine.analyze(nodeInput);
  assert.equal(result.analysis.startup.fallbackReason, 'handover-error'); assert.equal(reg.live(), 0);
  const ok = registry(() => ({best: 'e2e4'}));
  const e2 = createPrewarmedAnalyzer({createWorker: ok.create});
  await e2.prewarm();
  const r2 = await e2.analyze(nodeInput);
  assert.equal(r2.analysis.startup.path, 'spare'); assert.ok(r2.analysis.startup.waitedMs >= 0);
});

test('S3ii attack: a spare failing late leaves the fresh fallback its own full start-up budget', async () => {
  const made = [];
  const engine = createPrewarmedAnalyzer({prewarmTimeoutMs: 1800, createWorker: () => {
    const w = made.length === 0 ? new FakeWorker({ready: false})
      : new FakeWorker({ready: false, best: 'e2e4', onCommand: (c, x) => {
        if (c === 'uci') setTimeout(() => x.emit('message', 'uciok'), 500);
        if (c === 'isready') queueMicrotask(() => x.emit('message', 'readyok'));
        if (c.startsWith('go ')) queueMicrotask(() => x.emit('message', bm('e2e4')));
      }});
    made.push(w); return w;
  }});
  // Timeline (ms): spare silent and fails at 1800; analyze at 1000 waits; the fresh worker
  // answers uci after 500. The round-1 code gave it only the 400 ms left and timed out.
  engine.prewarm();
  await new Promise(r => setTimeout(r, 1000));
  const result = await engine.analyze(nodeInput, {startupTimeoutMs: 1200});
  assert.equal(result.bestMove.uci, 'e2e4'); assert.equal(made.length, 2);
  assert.equal(result.analysis.startup.path, 'fallback');
  assert.ok(['spare-failed', 'spare-not-ready'].includes(result.analysis.startup.fallbackReason));
  assert.ok(result.analysis.startup.waitedMs < 1200 + 1000 + 1200, 'bounded: wait + hand-over + fresh start-up');
});

test('S3ii: waiting on a warming spare is bounded by startupTimeoutMs, then a fresh worker', async t => {
  const timers = fakeTimers(t);
  const reg = registry(i => i === 0 ? {ready: false} : {best: 'e2e4'});
  const engine = createPrewarmedAnalyzer({createWorker: reg.create, clock: () => timers.now, prewarmTimeoutMs: 60000});
  engine.prewarm(); await settle();
  const pending = engine.analyze(nodeInput, {startupTimeoutMs: 5000}); await settle();
  timers.tick(5000); await settle();
  const result = await pending;
  assert.equal(result.analysis.startup.fallbackReason, 'spare-not-ready'); assert.equal(result.analysis.startup.waitedMs, 5000);
  assert.equal(reg.live(), 0); assert.equal(timers.pending, 0);
});

test('S3iii attack: prewarm during an analysis creates no second engine', async () => {
  const reg = registry(i => i === 0 ? {warm: 'manual', best: 'e2e4'} : {best: 'e2e4'});
  const engine = createPrewarmedAnalyzer({createWorker: reg.create});
  engine.prewarm(); await settle();
  const pending = engine.analyze(nodeInput); await settle();
  assert.equal(await engine.prewarm(), false);
  assert.equal(reg.workers.length, 1);
  engine.dispose(); await assert.rejects(pending, {code: 'ABORTED'});
  const fresh = registry(() => ({best: undefined}));
  const e2 = createPrewarmedAnalyzer({createWorker: fresh.create});
  const p2 = e2.analyze(nodeInput); await settle();
  assert.equal(await e2.prewarm(), false); assert.equal(fresh.workers.length, 1);
  e2.dispose(); await assert.rejects(p2, {code: 'ABORTED'});
});

test('S3iv attack: every prewarm caller\'s signal is honoured (any abort discards the shared spare)', async () => {
  for (const which of ['first', 'second']) {
    const reg = registry(() => ({best: 'e2e4', warm: 'manual'}));
    const engine = createPrewarmedAnalyzer({createWorker: reg.create});
    const c1 = new AbortController(), c2 = new AbortController();
    const p1 = engine.prewarm({signal: c1.signal}), p2 = engine.prewarm({signal: c2.signal});
    await settle();
    (which === 'first' ? c1 : c2).abort();
    await settle();
    assert.equal(reg.live(), 0, which + ': discarded at once, not at the start-up deadline');
    assert.equal(await p1, false); assert.equal(await p2, false);
    assert.equal(reg.live(), 0, which); assert.equal(engine.state().spare, null);
  }
});

test('S4: on the adopted path a result on time but processed after the search deadline is TIMEOUT', async () => {
  let completing = false, reads = 0;
  const reg = registry(() => ({best: undefined}));
  const engine = createPrewarmedAnalyzer({createWorker: reg.create, clock: () => completing ? (++reads === 1 ? 99 : 101) : 0});
  assert.equal(await engine.prewarm(), true);
  const pending = engine.analyze(nodeInput, {searchTimeoutMs: 100, graceMs: 0});
  await settle();
  assert.ok(reg.workers[0].commands.includes('go nodes 100000'));
  completing = true;
  reg.workers[0].emit('message', bm('e2e4'));
  await assert.rejects(pending, {code: 'TIMEOUT'});
  assert.equal(reg.workers[0].terminated, 1);
});

// ---------- real pinned WebAssembly engine (Node worker; not WebKit or iPhone evidence) ----------

test('real engine: prewarmed worker finds mate in one with a legal principal variation', async () => {
  const engine = createPrewarmedAnalyzer({createWorker: nodeWorker});
  assert.equal(await engine.prewarm(), true);
  const result = await engine.analyze({...nodeInput, fen: '7k/5Q2/6K1/8/8/8/8/8 w - - 0 1'});
  assert.equal(result.analysis.prewarmed, true);
  const chess = loadPosition(result.fen); chess.move(result.bestMove);
  assert.ok(chess.isCheckmate()); assert.equal(result.analysis.mate, 1);
  const replay = loadPosition(result.fen);
  for (const move of result.analysis.pv) assert.equal(replay.move({from: move.uci.slice(0,2), to: move.uci.slice(2,4), promotion: move.uci[4]}).san, move.san);
  engine.dispose();
});

test('real engine: go nodes 100000 returns a legal move on 10 varied positions (prewarmed)', async () => {
  const fens = [
    START_FEN,
    'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3',
    'rnbqkb1r/pp2pppp/3p1n2/8/3NP3/8/PPP2PPP/RNBQKB1R w KQkq - 1 5',
    'r2q1rk1/ppp2ppp/2np1n2/2b1p1B1/2B1P1b1/2NP1N2/PPP2PPP/R2Q1RK1 w - - 4 8',
    'r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10',
    '8/8/4k3/8/2p5/8/B2K4/8 w - - 0 1',
    '8/5pk1/6p1/8/8/6P1/5PK1/3R4 b - - 0 40',
    '7k/P7/8/8/8/8/8/K7 w - - 0 1',
    'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1',
    'rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3',
  ];
  // Generous prewarm/hand-over limits: the path, not the speed, is under test (Mac load reached 150).
  const engine = createPrewarmedAnalyzer({createWorker: nodeWorker, prewarmTimeoutMs: 60000, handoverTimeoutMs: 5000});
  for (const [index, fen] of fens.entries()) {
    assert.equal(await engine.prewarm(), true);
    // Generous wall-clock limit: this checks legality, not speed (a loaded Mac hit the 3 s default).
    const result = await engine.analyze({...nodeInput, fen, requestId: 'real-' + index}, {searchTimeoutMs: 30000});
    assert.equal(result.requestId, 'real-' + index); assert.equal(result.fen, fen);
    assert.ok(loadPosition(fen).move(result.bestMove), fen);
    assert.equal(result.analysis.prewarmed, true, JSON.stringify(result.analysis.startup));
    assert.ok(result.analysis.nodes >= 90000, `nodes ${result.analysis.nodes}`);
  }
  engine.dispose();
});

test('real engine: PV binding accepts 1000-node searches, a single legal move and an immediate mate', async () => {
  // Probe (round 2): go nodes 1000 on the start position printed 4 info lines, 3 with a PV (last upperbound).
  const engine = createPrewarmedAnalyzer({createWorker: nodeWorker});
  for (const [fen, expected] of [[START_FEN, null], ['7k/8/8/8/8/8/6q1/7K w - - 0 1', 'h1g2'], ['7k/5Q2/6K1/8/8/8/8/8 w - - 0 1', null]]) {
    const result = await engine.analyze({...nodeInput, fen, nodes: 1000});
    assert.ok(loadPosition(fen).move(result.bestMove));
    if (expected) assert.equal(result.bestMove.uci, expected);
  }
  engine.dispose();
});

// Opt-in (slow, ~2 to 4 minutes): fresh versus prewarmed best move on the 121-position set.
// PREWARM_IDENTITY_LADDER=/path/to/engine-budget ladder.json (rows with fen and budgets['100000'].move).
// Optional PREWARM_IDENTITY_RECORDED=/path/to/result-identity.json reuses recorded fresh moves and node
// counts instead of re-running fresh workers (half the engine time).
const ladderPath = process.env.PREWARM_IDENTITY_LADDER;
test('opt-in: prewarmed and fresh workers choose the same move on the 121-position set', {skip: ladderPath ? false : 'opt-in: PREWARM_IDENTITY_LADDER=/path/ladder.json', timeout: 900000}, async () => {
  const {readFileSync} = await import('node:fs');
  const rows = JSON.parse(readFileSync(ladderPath, 'utf8')).rows;
  const recordedPath = process.env.PREWARM_IDENTITY_RECORDED;
  const recorded = recordedPath ? new Map(JSON.parse(readFileSync(recordedPath, 'utf8')).identity.rows.map(r => [r.id, r])) : null;
  const diffs = [];
  for (const row of rows) {
    let fresh;
    if (recorded) fresh = {move: recorded.get(row.id).fresh, nodes: recorded.get(row.id).freshNodes};
    else {
      const f = createPrewarmedAnalyzer({createWorker: nodeWorker});
      const r = await f.analyze({...nodeInput, fen: row.fen}); f.dispose();
      fresh = {move: r.bestMove.uci, nodes: r.analysis.nodes};
    }
    const w = createPrewarmedAnalyzer({createWorker: nodeWorker});
    assert.equal(await w.prewarm(), true);
    const r = await w.analyze({...nodeInput, fen: row.fen}); w.dispose();
    assert.equal(r.analysis.prewarmed, true);
    if (r.bestMove.uci !== fresh.move || r.analysis.nodes !== fresh.nodes) diffs.push({id: row.id, fresh, prewarmed: {move: r.bestMove.uci, nodes: r.analysis.nodes}});
  }
  console.log(`identity: ${rows.length - diffs.length}/${rows.length} same move and node count`);
  assert.deepEqual(diffs, []);
});
