import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {Chess} from 'chess.js';

// Consistency of the special-move Replay game inside the iPhone app sources (2026-11-15):
// the frame pins in ReplayGame.swift and prepare_app.py agree, and the expected FENs/SANs typed into
// the self-test (SelfTest.swift) and the mock suite (ReplayGameChecks.swift) are the real game,
// replayed here with chess.js in the tracker's FEN convention. With SPECIAL_GAME_DIR set (output of
// scripts/simulation/generate-special-game.mjs) the pins and FENs are also checked against the
// generated pixels and the manifest's evaluatorTruth.
const app = new URL('../native/ChessCompanionApp/', import.meta.url);
const read = name => readFile(new URL(name, app), 'utf8');
const hexes = text => [...text.matchAll(/"([0-9a-f]{64})"/g)].map(m => m[1]);
const block = (text, start, end) => {
  const from = text.indexOf(start);
  assert.ok(from >= 0, `missing ${start}`);
  return text.slice(from, text.indexOf(end, from));
};
const strings = text => [...text.matchAll(/"([^"]+)"/g)].map(m => m[1]);
const SAN = ['e4', 'Nf6', 'e5', 'd5', 'exd6', 'Bf5', 'dxc7', 'Nbd7', 'cxd8=Q+', 'Rxd8', 'd4', 'e6', 'Nc3',
  'Be7', 'Be3', 'O-O', 'Qd2', 'Nb6', 'O-O-O', 'Nbd5', 'Nxd5', 'Nxd5', 'Bd3', 'Bxd3', 'Qxd3'];

function gameFens() {
  const chess = new Chess();
  const fens = [chess.fen({forceEnpassantSquare: true})];
  for (const san of SAN) {
    assert.equal(chess.move(san).san, san);
    fens.push(chess.fen({forceEnpassantSquare: true}));
  }
  return fens;
}

async function sources() {
  const swift = await read('ReplayGame.swift');
  const python = await read('prepare_app.py');
  const selfTest = await read('SelfTest.swift');
  const checks = await read('ReplayGameChecks.swift');
  const swiftPins = hexes(block(swift, 'private static let specialPins', ']'));
  const swiftInterruptions = hexes(block(swift, 'static let specialOcclusion', 'static var allAssetNames'));
  const pythonPins = hexes(block(python, 'SPECIAL_REPLAY_FRAMES = {', '\n}\n'));
  return {
    swiftPins, swiftInterruptions, pythonPins,
    selfTestFens: strings(block(selfTest, 'static let specialFENs = [', ']')),
    selfTestSan: strings(block(selfTest, 'static let specialSAN = [', ']')),
    checksFens: strings(block(checks, 'private let specialFENs = [', ']')),
    checksSan: [...block(checks, 'private let specialMoves', '\n]\n').matchAll(/"san": "([^"]+)"/g)].map(m => m[1]),
  };
}

test('special replay pins agree between ReplayGame.swift and prepare_app.py', async () => {
  const s = await sources();
  assert.equal(s.swiftPins.length, 26);
  assert.equal(s.swiftInterruptions.length, 2);
  assert.deepEqual(s.pythonPins, [...s.swiftPins, ...s.swiftInterruptions]);
});

test('self-test and mock suite carry the real special game (chess.js, tracker FEN convention)', async () => {
  const s = await sources();
  const fens = gameFens();
  assert.equal(fens.length, 26);
  assert.deepEqual(s.selfTestFens, fens);
  assert.deepEqual(s.checksFens, fens);
  assert.deepEqual(s.selfTestSan, SAN);
  assert.deepEqual(s.checksSan, SAN);
  assert.match(fens[4], / w KQkq d6 0 3$/, 'en-passant square after 2...d5');
  assert.match(fens[16], / w KQ - 4 9$/, 'black castled: white rights only');
  assert.match(fens[19], / b - - 7 10$/, 'both sides lost castling rights');
});

const directory = process.env.SPECIAL_GAME_DIR;
const skip = directory ? false : 'SPECIAL_GAME_DIR not set; special game output not available.';

test('pins and FENs match the generated special game', {skip}, async () => {
  const s = await sources();
  const manifest = JSON.parse(await readFile(join(directory, 'replay-manifest.json'), 'utf8'));
  const files = [...manifest.frames.map(f => f.file), ...manifest.interruptions.map(f => f.file)];
  const actual = [];
  for (const file of files) actual.push(createHash('sha256').update(await readFile(join(directory, 'pixels', file))).digest('hex'));
  assert.deepEqual(actual, s.pythonPins);
  assert.deepEqual(manifest.interruptions.map(i => i.playAfterFrameIndex), [20, 22]);
  assert.deepEqual(manifest.evaluatorTruth.frames.map(f => f.expectedFen), gameFens());
  assert.deepEqual(manifest.evaluatorTruth.moves, SAN);
});
