import test from 'node:test';
import assert from 'node:assert/strict';
import {Worker} from 'node:worker_threads';
import {createWorkerAnalyzer} from '../src/core/worker-engine.js';
import {START_FEN, loadPosition} from '../src/core/position.js';

const input = {fen: START_FEN, confirmation: true, movetimeMs: 50, requestId: 'worker-test'};
const turn = () => new Promise(resolve => setImmediate(resolve));

class FakeWorker {
  constructor({ready = true, best, info = [], onCommand} = {}) {
    this.listeners = new Map(); this.commands = []; this.terminated = 0;
    this.handle = command => {
      onCommand?.(command, this);
      if (ready && command === 'uci') queueMicrotask(() => this.emit('message', 'uciok'));
      if (ready && command === 'isready') queueMicrotask(() => this.emit('message', 'readyok'));
      if (command.startsWith('go ') && best !== undefined) queueMicrotask(() => {
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

test('worker handshake sets bounded hash, full position and one search; result matches Node analyzer shape', async () => {
  const worker = new FakeWorker({best: 'e2e4 ponder e7e5', info: ['info depth 12 score cp 25 pv e2e4 e7e5 g1f3']});
  const result = await createWorkerAnalyzer({createWorker: () => worker})(input);
  assert.deepEqual(worker.commands, ['uci', 'setoption name Hash value 32', 'isready', 'ucinewgame',
    'position fen ' + START_FEN, 'go movetime 50', 'stop', 'quit']);
  assert.equal(worker.terminated, 1);
  assert.deepEqual(Object.keys(result).sort(), ['analysis', 'bestMove', 'fen', 'requestId', 'speechText', 'status']);
  assert.equal(result.fen, START_FEN); assert.equal(result.requestId, input.requestId);
  assert.equal(result.bestMove.uci, 'e2e4'); assert.equal(result.bestMove.san, 'e4');
  assert.equal(result.speechText, 'pawn from e2 to e4.');
  assert.equal(result.analysis.depth, 12); assert.equal(result.analysis.scoreCp, 25);
  assert.deepEqual(result.analysis.pv.map(move => move.san), ['e4', 'e5', 'Nf3']);
  assert.equal(result.analysis.scorePerspective, 'side-to-move'); assert.equal(result.analysis.bounded, true);
  assert.ok(result.analysis.elapsedMs >= 0);
  assert.ok([...worker.listeners.values()].every(listeners => listeners.size === 0));
});

test('confirmation, complete FEN, time and deadline validation precede worker allocation', async () => {
  let allocations = 0;
  const analyze = createWorkerAnalyzer({createWorker: () => { allocations++; return new FakeWorker(); }});
  await assert.rejects(analyze({...input, confirmation: false}), {code: 'CONFIRMATION_REQUIRED'});
  await assert.rejects(analyze({...input, fen: START_FEN.split(' ')[0]}), /six-field FEN/);
  for (const movetimeMs of [49, 3001, NaN, 50.5]) await assert.rejects(analyze({...input, movetimeMs}), {code: 'INVALID_TIME'});
  for (const options of [{startupTimeoutMs: Infinity}, {startupTimeoutMs: 0}, {graceMs: -1}, {graceMs: 10001}]) {
    await assert.rejects(analyze(input, options), {code: 'INVALID_TIMEOUT'});
  }
  assert.equal(allocations, 0);
});

test('terminal positions return no move; pre-aborted requests never allocate', async () => {
  let allocations = 0;
  const analyze = createWorkerAnalyzer({createWorker: () => { allocations++; return new FakeWorker(); }});
  const result = await analyze({...input, fen: '7k/6Q1/5K2/8/8/8/8/8 b - - 0 1'});
  assert.equal(result.bestMove, null); assert.equal(result.speechText, null);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(analyze(input, {signal: controller.signal}), {code: 'ABORTED'});
  assert.equal(allocations, 0);
});

test('abort during creation, startup and search terminates exactly once', async () => {
  for (const phase of ['creation', 'startup', 'search']) {
    const controller = new AbortController();
    const worker = new FakeWorker({ready: phase === 'search'});
    const analyze = createWorkerAnalyzer({createWorker: () => {
      if (phase === 'creation') controller.abort();
      return worker;
    }});
    const pending = analyze(input, {signal: controller.signal});
    const rejected = assert.rejects(pending, {code: 'ABORTED'});
    if (phase === 'search') { await turn(); assert.ok(worker.commands.includes('go movetime 50')); }
    controller.abort(); await rejected;
    assert.equal(worker.terminated, 1);
    if (phase === 'creation') assert.deepEqual(worker.commands, ['stop', 'quit']);
  }
});

test('startup and search deadlines terminate silent workers', async () => {
  for (const ready of [false, true]) {
    const worker = new FakeWorker({ready});
    await assert.rejects(createWorkerAnalyzer({createWorker: () => worker})(input, {startupTimeoutMs: 30, graceMs: 5}), {code: 'TIMEOUT'});
    assert.equal(worker.terminated, 1);
  }
});

test('duplicate or early handshakes never restart or bypass startup', async () => {
  const worker = new FakeWorker({ready: false});
  const pending = createWorkerAnalyzer({createWorker: () => worker})(input);
  worker.emit('message', 'readyok'); assert.deepEqual(worker.commands, ['uci']);
  worker.emit('message', 'uciok\nuciok\nreadyok\nreadyok\nuciok');
  assert.equal(worker.commands.filter(command => command === 'isready').length, 1);
  assert.equal(worker.commands.filter(command => command.startsWith('go ')).length, 1);
  worker.emit('message', 'bestmove e2e4'); await pending;
  const early = new FakeWorker({ready: false});
  const earlyResult = createWorkerAnalyzer({createWorker: () => early})(input);
  early.emit('message', 'bestmove e2e4');
  await assert.rejects(earlyResult, {code: 'ENGINE_PROTOCOL'});
});

test('malformed, illegal and spurious-promotion best moves are rejected', async () => {
  for (const best of ['e2e5', 'e2e4q', 'e2e4junk', '(none)', '0000', '', 'e2e4 unexpected', 'e2e4 ponder invalid']) {
    const worker = new FakeWorker({best});
    await assert.rejects(createWorkerAnalyzer({createWorker: () => worker})(input), {code: 'INVALID_ENGINE_MOVE'});
    assert.equal(worker.terminated, 1);
  }
  const result = await createWorkerAnalyzer({createWorker: () => new FakeWorker({best: 'a7a8n'})})(
    {...input, fen: '7k/P7/8/8/8/8/8/K7 w - - 0 1'});
  assert.equal(result.bestMove.promotion, 'n'); assert.match(result.speechText, /promote to knight/);
});

test('only wholly legal first-variation PV and safe exact scores are retained', async () => {
  const info = [
    'info depth 4 score cp 12 pv e2e4 e7e5',
    'info depth 7 score cp 90 pv e2e4 e7e6 e4e6',
    'info depth 8 score cp 91 pv e2e4q',
    'info depth 9 score cp 92 lowerbound pv d2d4',
    'info depth 10 multipv 2 score cp 93 pv d2d4',
    'info depth 999999999999999999999 score cp 94 pv d2d4',
    'info depth 12 score cp 999999999999999999999 pv d2d4',
    'info depth 13 score cp 95 pv ' + Array(257).fill('e2e4').join(' ')
  ];
  const result = await createWorkerAnalyzer({createWorker: () => new FakeWorker({best: 'e2e4', info})})(input);
  assert.equal(result.analysis.depth, 4); assert.equal(result.analysis.scoreCp, 12);
  assert.deepEqual(result.analysis.pv.map(move => move.uci), ['e2e4', 'e7e5']);
});

test('non-text, oversized and cumulative UTF-8 output terminate workers', async () => {
  for (const messages of [[{}], ['x'.repeat(1024*1024+1)], ['é'.repeat(530000)], Array(1025).fill('x'.repeat(1024))]) {
    const worker = new FakeWorker({ready: false});
    const pending = createWorkerAnalyzer({createWorker: () => worker})(input);
    for (const data of messages) worker.emit('message', data);
    await assert.rejects(pending, {code: 'ENGINE_OUTPUT'});
    assert.equal(worker.terminated, 1);
  }
});

test('worker failure, decoding failure and command errors reject and terminate', async () => {
  for (const event of ['error', 'messageerror']) {
    const worker = new FakeWorker({ready: false});
    const pending = createWorkerAnalyzer({createWorker: () => worker})(input);
    worker.emit(event, undefined);
    await assert.rejects(pending, {code: event === 'error' ? 'ENGINE_ERROR' : 'ENGINE_OUTPUT'});
    assert.equal(worker.terminated, 1);
  }
  const worker = new FakeWorker({onCommand: command => { if (command === 'uci') throw new Error(); }});
  await assert.rejects(createWorkerAnalyzer({createWorker: () => worker})(input), {code: 'ENGINE_ERROR'});
  assert.equal(worker.terminated, 1);
});

test('private workers isolate overlapping searches and late callbacks; reused workers reject without killing owner', async () => {
  const first = new FakeWorker(), second = new FakeWorker();
  const queue = [first, second];
  const analyze = createWorkerAnalyzer({createWorker: () => queue.shift()});
  const controller = new AbortController();
  const old = analyze({...input, requestId: 'old'}, {signal: controller.signal});
  const rejected = assert.rejects(old, {code: 'ABORTED'});
  const late = [...first.listeners.get('message')][0];
  const current = analyze({...input, requestId: 'new'});
  await turn();
  controller.abort(); await rejected;
  late({data: 'bestmove d2d4'}); late({data: 'uciok'});
  assert.equal(second.terminated, 0);
  second.emit('message', 'bestmove e2e4');
  const result = await current;
  assert.equal(result.requestId, 'new'); assert.equal(result.bestMove.uci, 'e2e4');
  second.emit('message', 'bestmove d2d4'); assert.equal(second.terminated, 1);

  const shared = new FakeWorker();
  const sharedAnalyzer = createWorkerAnalyzer({createWorker: () => shared});
  const owner = sharedAnalyzer(input);
  await assert.rejects(sharedAnalyzer(input), {code: 'WORKER_REUSED'});
  assert.equal(shared.terminated, 0);
  await turn(); shared.emit('message', 'bestmove e2e4'); await owner;
});

test('monotonic clock controls elapsed and detects overdue callbacks or invalid values', async () => {
  let time = 100;
  const worker = new FakeWorker();
  const pending = createWorkerAnalyzer({createWorker: () => worker, clock: () => time})(input);
  await turn(); time = 125; worker.emit('message', 'bestmove e2e4');
  assert.equal((await pending).analysis.elapsedMs, 25);
  const overdue = new FakeWorker({ready: false});
  const late = createWorkerAnalyzer({createWorker: () => overdue, clock: () => time})(input, {startupTimeoutMs: 20});
  time += 21; overdue.emit('message', 'uciok'); await assert.rejects(late, {code: 'TIMEOUT'});
  for (const clock of [() => NaN, () => { throw undefined; }]) {
    await assert.rejects(createWorkerAnalyzer({createWorker: () => new FakeWorker(), clock})(input), {code: 'INVALID_CLOCK'});
  }
});

test('a message arriving on time cannot publish after result processing crosses the search deadline', async () => {
  let completing = false, reads = 0;
  const worker = new FakeWorker();
  const clock = () => completing ? (++reads === 1 ? 49 : 51) : 0;
  const pending = createWorkerAnalyzer({createWorker: () => worker, clock})(input, {graceMs: 0});
  await turn(); completing = true;
  worker.emit('message', 'bestmove e2e4');
  await assert.rejects(pending, {code: 'TIMEOUT'});
  assert.equal(worker.terminated, 1);
});

test('a ready message cannot replace an expired startup deadline with a search deadline', async () => {
  let reads = 0;
  const worker = new FakeWorker({ready: false});
  const clock = () => ++reads <= 2 ? 0 : 11;
  const pending = createWorkerAnalyzer({createWorker: () => worker, clock})(input, {startupTimeoutMs: 10});
  worker.emit('message', 'uciok\nreadyok');
  await assert.rejects(pending, {code: 'TIMEOUT'});
  assert.equal(worker.terminated, 1);
  assert.ok(!worker.commands.includes('ucinewgame'));
  assert.ok(!worker.commands.some(command => command.startsWith('go ')));
});

test('actual pinned Stockfish WebAssembly runs in Node worker and returns legal PV; not browser or iOS evidence', async () => {
  const result = await createWorkerAnalyzer({createWorker: nodeWorker})(input);
  assert.equal(result.requestId, input.requestId); assert.equal(result.fen, START_FEN);
  assert.ok(result.analysis.depth > 0); assert.ok(result.analysis.pv.length > 0);
  assert.ok(loadPosition(result.fen).move(result.bestMove));
  const replay = loadPosition(result.fen);
  for (const move of result.analysis.pv) assert.equal(replay.move({from: move.uci.slice(0,2), to: move.uci.slice(2,4), promotion: move.uci[4]}).san, move.san);
});

test('actual pinned WebAssembly worker finds mate in one and can be cancelled', async () => {
  const analyze = createWorkerAnalyzer({createWorker: nodeWorker});
  const result = await analyze({...input, fen: '7k/5Q2/6K1/8/8/8/8/8 w - - 0 1', movetimeMs: 100});
  const chess = loadPosition(result.fen); chess.move(result.bestMove);
  assert.ok(chess.isCheckmate()); assert.equal(result.analysis.mate, 1);
  const controller = new AbortController();
  const pending = analyze({...input, movetimeMs: 3000}, {signal: controller.signal});
  setTimeout(() => controller.abort(), 50);
  await assert.rejects(pending, {code: 'ABORTED'});
});
