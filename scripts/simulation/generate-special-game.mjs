#!/usr/bin/env node
/** Render one fixed, longer synthetic IMAGE game that contains a capture, castling on
 * both wings (kingside by one side, queenside by the other), an en passant capture and
 * a promotion, plus two interruption frames (one occluded, one with a piece missing).
 *
 * Pixels come from the existing renderer (scripts/simulation/render.py, same known
 * classic artwork) with one fixed, clean, un-distorted development scene. Output uses
 * the replay-manifest schema of select-replay-sequence.mjs; position facts appear only
 * under evaluatorTruth. Deterministic: no clocks, absolute paths or random values.
 */
import {Chess} from 'chess.js';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {mkdir, readFile, readdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
export const FRAME_SPACING_MS = 100;
/** 13.Qxd3 ends a 25-ply game from the standard start. */
export const GAME = Object.freeze(['e4', 'Nf6', 'e5', 'd5', 'exd6', 'Bf5', 'dxc7', 'Nbd7', 'cxd8=Q+', 'Rxd8',
  'd4', 'e6', 'Nc3', 'Be7', 'Be3', 'O-O', 'Qd2', 'Nb6', 'O-O-O', 'Nbd5', 'Nxd5', 'Nxd5', 'Bd3', 'Bxd3', 'Qxd3']);
/** Fixed clean development scene: classic templates, identity panel placement, no perspective change. */
export const SCENE = Object.freeze({style: 'classic', quad: [[64, 64], [704, 64], [704, 704], [64, 704]],
  brightness: 1, blur: 0.1, boardVariation: false});
const OCCLUSION = Object.freeze({box: [210, 90, 390, 300], color: [149, 111, 88]}); // same box as challenge-occlusion
const SPECIAL_FLAGS = {c: 'capture', e: 'en-passant', k: 'kingside-castle', q: 'queenside-castle', p: 'promotion'};
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const fail = message => { throw new Error(message); };
const pad = i => String(i).padStart(3, '0');

export function buildGame() {
  const chess = new Chess();
  const positions = [{ply: 0, moveSan: null, flags: '', fen: chess.fen({forceEnpassantSquare: true})}];
  GAME.forEach((san, i) => {
    const move = chess.move(san); // throws on an illegal move
    if (move.san !== san) fail(`Non-canonical SAN ${san}`);
    positions.push({ply: i + 1, moveSan: move.san, flags: move.flags, fen: chess.fen({forceEnpassantSquare: true})});
  });
  const kinds = [...new Set(positions.flatMap(p => [...p.flags].filter(f => SPECIAL_FLAGS[f]).map(f => SPECIAL_FLAGS[f])))].sort();
  for (const required of Object.values(SPECIAL_FLAGS)) if (!kinds.includes(required)) fail(`Game lacks ${required}`);
  const castles = positions.filter(p => /[kq]/.test(p.flags)).map(p => [p.ply % 2 ? 'w' : 'b', p.flags]);
  if (new Set(castles.map(([side]) => side)).size !== 2) fail('Each side must castle once on a different wing.');
  return {positions, kinds};
}

/** Remove one piece from a FEN placement (an illegal jump from the tracked position). */
function withoutPiece(fen, square) {
  const chess = new Chess(fen);
  if (!chess.remove(square)) fail(`No piece on ${square}`);
  return chess.fen().split(' ')[0];
}

export async function generateSpecialGame(out) {
  out = path.resolve(out);
  if (out === ROOT || out.startsWith(ROOT + path.sep)) fail('Generated media must stay outside the source repository.');
  await mkdir(out, {recursive: true});
  if ((await readdir(out)).length) fail('Output directory must be empty; existing artifacts are preserved.');
  const pixels = path.join(out, 'pixels');
  await mkdir(pixels);
  const {positions, kinds} = buildGame();
  const occludedAfter = 20, missingAfter = 22, missingSquare = 'h2';
  const interruptions = [
    {afterIndex: occludedAfter, kind: 'occluded', placement: positions[occludedAfter].fen.split(' ')[0],
      scene: {...SCENE, occlusions: [OCCLUSION]}, expectedReason: 'uncertain-squares',
      purpose: 'Occluded frame inserted mid-game; replay must withhold or revoke tracking.'},
    {afterIndex: missingAfter, kind: 'piece-missing', placement: withoutPiece(positions[missingAfter].fen, missingSquare),
      scene: SCENE, expectedReason: 'not-zero-or-one-legal-move',
      purpose: 'Frame with one piece missing (no legal move explains it); replay must revoke tracking.'}];
  const renders = [...positions.map(p => ({fen: p.fen, scene: SCENE})), ...interruptions.map(x => ({fen: `${x.placement} w - - 0 1`, scene: x.scene}))]
    .map((render, i) => ({...render, output: path.join(pixels, `frame-${pad(i)}.png`)}));
  const run = spawnSync('python3', ['-B', path.join(HERE, 'render.py')], {input: JSON.stringify({renders}),
    encoding: 'utf8', maxBuffer: 16 * 1024 * 1024, timeout: 120_000});
  if (run.error || run.status !== 0) fail(`Synthetic renderer failed: ${run.error?.message ?? run.stderr}`);
  const rendered = JSON.parse(run.stdout);
  if (rendered.length !== renders.length) fail('Renderer frame count mismatch.');
  const copies = [];
  for (const [i, render] of renders.entries()) {
    const digest = sha256(await readFile(render.output));
    if (digest !== rendered[i].sourceSha256) fail(`Rendered frame ${i} hash mismatch.`);
    copies.push({index: i, file: path.basename(render.output), sha256: digest, timestampMs: i * FRAME_SPACING_MS});
  }
  const main = copies.slice(0, positions.length), extra = copies.slice(positions.length);
  const visibleInterruptions = interruptions.map((x, i) => ({file: extra[i].file, sha256: extra[i].sha256,
    playAfterFrameIndex: x.afterIndex, purpose: x.purpose}));
  const manifest = {
    schemaVersion: 1,
    kind: 'offline-replay-sequence',
    generator: 'scripts/simulation/generate-special-game.mjs',
    source: {rendererSha256: sha256(await readFile(path.join(HERE, 'render.py'))),
      appearanceSha256: sha256(await readFile(path.join(HERE, 'appearance.py'))),
      description: 'Freshly rendered synthetic known-template frames (classic artwork, clean scene); not physical-board images.'},
    frames: main.map(({index, file, sha256, timestampMs}) => ({index, file, sha256, timestampMs})),
    interruption: visibleInterruptions[0],
    interruptions: visibleInterruptions,
    evaluatorTruth: {
      notice: 'Evaluator/test-fixture data only. A replay player must not feed this to recognition or tracking; the starting state stands in for one explicit human review.',
      sessionId: 'special-game', split: 'dev', startingFen: positions[0].fen,
      startingStateSource: 'synthetic-test-fixture', historyKnownFromInitial: true,
      fenConvention: 'chess.js fen({forceEnpassantSquare:true}), the tracker convention',
      specialMoveKinds: kinds, moves: [...GAME],
      frames: positions.map((p, i) => ({index: i, ply: p.ply, moveSan: p.moveSan,
        moveKinds: [...p.flags].filter(f => SPECIAL_FLAGS[f]).map(f => SPECIAL_FLAGS[f]), expectedFen: p.fen})),
      interruption: {kind: interruptions[0].kind, expectedAbstention: true, expectedTracking: 'withheld-or-revoked'},
      interruptions: interruptions.map((x, i) => ({file: extra[i].file, kind: x.kind, playAfterFrameIndex: x.afterIndex,
        renderedPlacement: x.placement, ...(x.kind === 'piece-missing' ? {missingSquare} : {occlusion: OCCLUSION}),
        expectedReason: x.expectedReason, expectedTracking: 'revoked-until-renewed-review',
        renewedReviewFen: positions[x.afterIndex].fen})),
      scene: SCENE
    }
  };
  const text = JSON.stringify(manifest, null, 2) + '\n';
  await writeFile(path.join(out, 'replay-manifest.json'), text, {flag: 'wx'});
  const index = {schemaVersion: 1, mode: 'synthetic-pixels',
    frames: copies.map(({file, timestampMs}) => ({id: file.replace('.png', ''), file, timestampMs}))};
  await writeFile(path.join(pixels, 'index.json'), JSON.stringify(index, null, 2) + '\n', {flag: 'wx'});
  return {manifestSha256: sha256(text), frames: main.length, interruptions: extra.length, plies: GAME.length,
    specialMoveKinds: kinds, frameHashes: copies.map(c => c.sha256)};
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const args = process.argv.slice(2);
  if (args.length !== 2 || args[0] !== '--out') {
    console.error('Usage: node scripts/simulation/generate-special-game.mjs --out OUTPUT_DIR'); process.exitCode = 1;
  } else {
    try { const {frameHashes, ...summary} = await generateSpecialGame(args[1]);
      console.log(JSON.stringify({...summary, framesSha256: sha256(frameHashes.join('\n'))})); }
    catch (error) { console.error(`Special game generation failed: ${error.message}`); process.exitCode = 1; }
  }
}
