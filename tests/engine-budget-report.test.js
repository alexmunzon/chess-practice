import test from 'node:test';
import assert from 'node:assert/strict';
import {Chess} from 'chess.js';
import {loadPosition} from '../src/core/position.js';
import {Engine, TACTICS, generatePositions, positionListSha, scoreToCp, moveLoss, percentile, phaseOf,
  mulberry32, parseInfo, CLAMP_CP} from '../scripts/engine-budget-report.mjs';

test('score clamping, loss and percentile follow the documented method', () => {
  assert.equal(scoreToCp({cp: 35}), 35);
  assert.equal(scoreToCp({cp: 5000}), CLAMP_CP);
  assert.equal(scoreToCp({mate: 3}), CLAMP_CP);
  assert.equal(scoreToCp({mate: -1}), -CLAMP_CP);
  assert.deepEqual(moveLoss({cp: 50}, {cp: -70}), {loss: 120, negative: false});
  assert.deepEqual(moveLoss({cp: 10}, {cp: 30}), {loss: 0, negative: true});
  assert.deepEqual(moveLoss({mate: 2}, {cp: 400}), {loss: 600, negative: false});
  assert.equal(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 100], 0.95), 19);
  assert.equal(percentile([0, 0, 0, 500], 0.5), 0);
});

test('phase labels, seeded generator and UCI info parsing are deterministic', () => {
  assert.equal(phaseOf(new Chess().fen()), 'opening');
  assert.equal(phaseOf('8/5pk1/8/8/8/8/5PK1/3R4 w - - 0 40'), 'endgame');
  const a = mulberry32(42), b = mulberry32(42);
  assert.deepEqual([a(), a(), a()], [b(), b(), b()]);
  const info = parseInfo('info depth 14 seldepth 20 multipv 1 score cp -31 nodes 100027 nps 290000 time 345 pv e2e4 e7e5');
  assert.equal(info.depth, 14); assert.deepEqual(info.score, {cp: -31}); assert.equal(info.nodes, 100027);
  assert.deepEqual(info.pv, ['e2e4', 'e7e5']); assert.equal(info.bound, false);
  assert.equal(parseInfo('info depth 3 score mate 2 lowerbound nodes 9 pv d2d8').bound, true);
});

test('hand-written tactical positions are legal for the app and their intended moves are legal', () => {
  assert.ok(TACTICS.length >= 15);
  for (const t of TACTICS) {
    const chess = loadPosition(t.fen);
    assert.ok(chess.move({from: t.best.slice(0, 2), to: t.best.slice(2, 4), ...(t.best[4] ? {promotion: t.best[4]} : {})}), t.id);
  }
});

test('pinned WASM engine: mate in one at a 5k-node budget; same seed gives the same positions (Mac Node worker only)', async () => {
  const engine = new Engine();
  try {
    await engine.start();
    const mate = await engine.search('7k/5Q2/6K1/8/8/8/8/8 w - - 0 1', {nodes: 5000});
    const chess = loadPosition('7k/5Q2/6K1/8/8/8/8/8 w - - 0 1');
    chess.move({from: mate.bestmove.slice(0, 2), to: mate.bestmove.slice(2, 4)});
    assert.ok(chess.isCheckmate()); assert.deepEqual(mate.score, {mate: 1});
    const opts = {count: 4, seed: 7, maxGames: 2, maxPlies: 36};
    const first = await generatePositions(engine, opts);
    const second = await generatePositions(engine, opts);
    assert.ok(first.positions.length >= 1);
    assert.equal(positionListSha(first.positions), positionListSha(second.positions));
    const other = await generatePositions(engine, {...opts, seed: 8});
    assert.notEqual(positionListSha(other.positions), positionListSha(first.positions));
  } finally { await engine.quit(); }
});
