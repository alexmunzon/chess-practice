import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { Chess } from 'chess.js';
import { SQUARES } from '../src/core/observation.js';
import { evaluateDataset, scorePrediction } from '../scripts/simulation/evaluate.mjs';

const initial = new Chess().fen(), digest = bytes => createHash('sha256').update(bytes).digest('hex');
function squares(fen) {
  const chess = new Chess(fen);
  return Object.fromEntries(SQUARES.map(square => { const p = chess.get(square); return [square, p ? (p.color === 'w' ? p.type.toUpperCase() : p.type) : '.']; }));
}
function prediction(fen, bytes, { unknown = false, unavailable = false } = {}) {
  return { schemaVersion: 1, source: 'synthetic-pixel-inference', sourceSha256: digest(bytes), status: 'needs-human-review',
    fen: null, guidanceAllowed: false, threshold: 0.95,
    squares: Object.fromEntries(Object.entries(squares(fen)).map(([square, raw]) => [square,
      { rawLabel: unavailable ? '.' : raw, rawLabelAvailable: !unavailable, confidence: unknown || unavailable ? 0 : 1,
        label: unknown || unavailable ? 'unknown' : raw === '.' ? 'empty' : raw }])) };
}
async function fixture(t, definitions) {
  const root = await mkdtemp(join(tmpdir(), 'chess-evaluator-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, 'pixels')); await mkdir(join(root, 'evaluator'));
  const frames = [], truths = [], sessions = [], predictions = new Map();
  for (const [sessionIndex, definition] of definitions.entries()) {
    const id = `session-${sessionIndex}`, states = definition.states ?? [initial, initial];
    sessions.push({ id, initialFen: states[0], historyDescription: 'Synthetic automated fixture; pre-fixture repetition history unknown.' });
    for (const [i, fen] of states.entries()) {
      const frameId = `f${frames.length}`, file = `${String(frames.length).padStart(6, '0')}.png`, timestampMs = frames.length * 100;
      // Unit test tokens, not image-inference evidence. Real adapters are separately exercised by CLI.
      const bytes = Buffer.from(`test-image-token:${frameId}`);
      await writeFile(join(root, 'pixels', file), bytes);
      frames.push({ id: frameId, file, timestampMs });
      truths.push({ id: frameId, session: id, split: definition.split ?? 'dev', fen, squares: squares(fen), scene: {}, timestampMs,
        sourceSha256: digest(bytes), expectedAbstention: definition.split === 'challenge' });
      predictions.set(bytes.toString(), definition.predict?.(fen, bytes, i) ?? prediction(fen, bytes));
    }
  }
  await writeFile(join(root, 'pixels/index.json'), JSON.stringify({ schemaVersion: 1, mode: 'synthetic-pixels', frames }));
  await writeFile(join(root, 'evaluator/truth.json'), JSON.stringify({ frames: truths, sessions }));
  const calls = [];
  const recognizer = async function (...args) {
    calls.push(args); const value = predictions.get(args[0].toString());
    if (value instanceof Error) throw value;
    return structuredClone(value);
  };
  const engineCalls = [];
  const engine = async request => {
    engineCalls.push(request);
    const chess = new Chess(request.fen), move = chess.moves({ verbose: true })[0];
    return { requestId: request.requestId, fen: request.fen, bestMove: move ? { from: move.from, to: move.to, ...(move.promotion ? { promotion: move.promotion } : {}) } : null };
  };
  return { root, recognizer, engine, calls, engineCalls, predictions, frames };
}

test('synthetic evaluator passes only bytes, uses tracked state for engine and text, and exercises stale gate', async t => {
  const f = await fixture(t, [{}, { split: 'heldout' }, { split: 'challenge', predict: (fen, bytes) => prediction(fen, bytes, { unknown: true }) }]);
  const report = await evaluateDataset({ input: f.root, recognizer: f.recognizer, engine: f.engine });
  assert.equal(report.passed, true);
  assert.ok(f.calls.every(args => args.length === 1 && Buffer.isBuffer(args[0])));
  assert.equal(f.engineCalls.length, 1); assert.equal(report.engine.speechMessages.length, 1);
  assert.equal(report.engine.speechMessages[0].mode, 'text-only');
  assert.match(report.review, /AUTOMATED REVIEW FIXTURE/); assert.equal(report.historyComplete, false);
  assert.equal(report.recognitionAdapter, 'test-injected');
  assert.ok(report.staleProbes.every(p => p.passed && p.engineCalls === 0 && p.additionalSpeechMessages === 0));
  assert.equal(report.splits.challenge.engineCalls, 0); assert.equal(report.splits.challenge.abstentionViolations, 0);
});

test('source hash, pixel-only manifest, and initial fixture mismatch fail before recognition', async t => {
  for (const alter of [
    async f => writeFile(join(f.root, 'pixels', f.frames[0].file), 'replaced-image'),
    async f => { const path = join(f.root, 'pixels/index.json'), data = JSON.parse(await readFile(path)); data.frames[0].fen = initial; await writeFile(path, JSON.stringify(data)); },
    async f => { const path = join(f.root, 'evaluator/truth.json'), data = JSON.parse(await readFile(path)); const chess = new Chess(); chess.move('e4'); data.sessions[0].initialFen = chess.fen(); await writeFile(path, JSON.stringify(data)); },
  ]) {
    const f = await fixture(t, [{}]); await alter(f);
    await assert.rejects(evaluateDataset({ input: f.root, recognizer: f.recognizer, engine: f.engine }));
    assert.equal(f.calls.length, 0); assert.equal(f.engineCalls.length, 0);
  }
});

test('unavailable raw predictions never earn empty-square or exact-board credit', () => {
  const bytes = Buffer.from('missing-board');
  const score = scorePrediction(prediction(initial, bytes, { unavailable: true }), squares(initial));
  assert.equal(score.rawAvailableSquares, 0); assert.equal(score.rawCorrectSquares, 0);
  assert.equal(score.rawExactBoard, false); assert.equal(score.unknownSquares, 64);
});

test('unknown, thrown, and malformed inference revoke ready state without automatic reconfirmation', async t => {
  for (const kind of ['unknown', 'throw', 'malformed']) {
    const f = await fixture(t, [{ states: Array(6).fill(initial), predict: (fen, bytes, i) => {
      if (i !== 2) return prediction(fen, bytes);
      if (kind === 'throw') return new Error('inference failed');
      const p = prediction(fen, bytes, { unknown: true });
      if (kind === 'malformed') delete p.squares.a1;
      return p;
    } }, { split: 'heldout' }]);
    const report = await evaluateDataset({ input: f.root, recognizer: f.recognizer, engine: f.engine });
    assert.equal(report.frames[1].tracker.guidanceAllowed, true);
    assert.ok(report.frames.slice(2, 6).every(frame => !frame.tracker.guidanceAllowed));
    assert.equal(report.splits.dev.totalSquares, 384); assert.equal(report.splits.dev.unknownSquares, 64);
    assert.equal(report.passed, false);
  }
});

test('legal but wrong accepted observations count as board and complete-state failures', async t => {
  const chess = new Chess(); chess.move('e4'); const wrong = chess.fen({ forceEnpassantSquare: true });
  const f = await fixture(t, [{ states: Array(4).fill(initial), predict: (fen, bytes, i) => prediction(i >= 2 ? wrong : fen, bytes) }, { split: 'heldout' }]);
  const report = await evaluateDataset({ input: f.root, recognizer: f.recognizer, engine: f.engine });
  assert.equal(report.splits.dev.acceptedWrongBoards, 2); assert.equal(report.splits.dev.readyWrongStates, 1);
  assert.equal(report.frames[3].tracker.fen, wrong); assert.equal(report.safetyPassed, false);
});

test('all-unknown heldout cannot pass on a successful development example', async t => {
  const f = await fixture(t, [{}, { split: 'heldout', predict: (fen, bytes) => prediction(fen, bytes, { unknown: true }) }]);
  const report = await evaluateDataset({ input: f.root, recognizer: f.recognizer, engine: f.engine });
  assert.equal(report.safetyPassed, true); assert.equal(report.engineTextPassed, true);
  assert.equal(report.positiveCoveragePassed, false); assert.equal(report.passed, false);
});

test('exact pixel boards cannot mask skipped-ply tracking failure', async t => {
  const chess = new Chess(); chess.move('e4'); chess.move('e5'); const skipped = chess.fen({ forceEnpassantSquare: true });
  const f = await fixture(t, [{ states: [initial, initial, skipped, skipped] }, { split: 'heldout' }]);
  const report = await evaluateDataset({ input: f.root, recognizer: f.recognizer, engine: f.engine });
  assert.equal(report.positiveCoveragePassed, true); assert.equal(report.engineTextPassed, true);
  assert.equal(report.frames[3].tracker.reason, 'not-zero-or-one-legal-move');
  assert.equal(report.splits.dev.missedReadyStates, 1); assert.equal(report.trackingCoveragePassed, false);
  assert.equal(report.passed, false);
});

test('challenge confident boards fail even before stability and use the same guidance gate', async t => {
  const f = await fixture(t, [{}, { split: 'heldout' }, { split: 'challenge' }]);
  const report = await evaluateDataset({ input: f.root, recognizer: f.recognizer, engine: f.engine });
  assert.equal(report.splits.challenge.abstentionViolations, 2);
  assert.equal(report.frames[4].tracker.guidanceAllowed, false);
  assert.equal(report.splits.challenge.engineCalls, 1); assert.equal(f.engineCalls.length, 2);
  assert.equal(report.passed, false);
});

test('recognized squares track castling, en passant, promotion and full metadata from explicit fixture', async t => {
  const definitions = [
    ['r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1', 'O-O'],
    ['4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2', 'exd6'],
    ['7k/P7/8/8/8/8/8/7K w - - 0 1', { from: 'a7', to: 'a8', promotion: 'n' }],
  ].map(([fen, move]) => { const chess = new Chess(fen); chess.move(move); const after = chess.fen({ forceEnpassantSquare: true }); return { states: [fen, fen, after, after] }; });
  const f = await fixture(t, [...definitions, { split: 'heldout' }]);
  const report = await evaluateDataset({ input: f.root, recognizer: f.recognizer, engine: f.engine });
  for (const index of [3, 7, 11]) { assert.equal(report.frames[index].tracker.guidanceAllowed, true); assert.equal(report.frames[index].tracker.fenMatchesTruth, true); }
  assert.equal(report.splits.dev.readyWrongStates, 0); assert.equal(report.passed, true);
});

test('mismatched or illegal engine results never produce text', async t => {
  for (const bad of ['identity', 'move']) {
    const f = await fixture(t, [{}, { split: 'heldout' }]);
    const engine = async request => ({ requestId: bad === 'identity' ? 'old-result' : request.requestId, fen: request.fen, bestMove: { from: 'e2', to: 'e5' } });
    const report = await evaluateDataset({ input: f.root, recognizer: f.recognizer, engine });
    assert.equal(report.engine.speechMessages.length, 0); assert.equal(report.engineTextPassed, false);
    assert.ok(report.frames[1].engine.error);
  }
});
