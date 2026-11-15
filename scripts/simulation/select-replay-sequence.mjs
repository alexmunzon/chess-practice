#!/usr/bin/env node
/** Select one contiguous legal game segment plus one interruption frame from an
 * existing synthetic corpus for the offline "Replay game" mode.
 *
 * Reads the corpus (pixels/index.json, evaluator/truth.json) without modifying it,
 * copies the chosen PNGs byte-for-byte into OUT/pixels/ under opaque names, and
 * writes OUT/pixels/index.json (same schema the native conformance runner reads)
 * and OUT/replay-manifest.json. Position facts appear only under evaluatorTruth.
 * Output is deterministic: no clocks, absolute paths or random values.
 */
import {createHash} from 'node:crypto';
import {copyFile, mkdir, readFile, readdir, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {Chess} from 'chess.js';

export const MIN_FRAMES = 8;
export const MAX_FRAMES = 20;
export const FRAME_SPACING_MS = 100;
const SPECIAL_FLAGS = {c: 'capture', e: 'en-passant', k: 'kingside-castle', q: 'queenside-castle', p: 'promotion'};
const CHALLENGE_PREFERENCE = ['challenge-occlusion', 'challenge-glare', 'challenge-missing-marker',
  'challenge-severe-blur', 'challenge-unfamiliar'];

const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const fail = message => { throw new Error(message); };

/** Replays each session's listed moves with chess.js and returns ply -> full FEN. */
function legalFens(session) {
  const chess = new Chess(session.initialFen);
  if (chess.fen() !== session.initialFen) fail(`Session ${session.id} initial FEN is not canonical.`);
  const fens = [chess.fen()], moves = [];
  for (const san of session.moves) {
    const move = chess.move(san); // Throws on an illegal move.
    fens.push(chess.fen()); moves.push({san: move.san, flags: move.flags});
  }
  return {fens, moves};
}

/** Maximal runs of clean, same-session frames where every ply advances by 0 or 1
 * and the truth FEN equals the legally replayed FEN. */
function candidateRuns(truth) {
  const sessions = new Map(truth.sessions.map(session => [session.id, {...session, ...legalFens(session)}]));
  const runs = [];
  let run = null;
  truth.frames.forEach((frame, position) => {
    const session = sessions.get(frame.session);
    const clean = session && frame.split !== 'challenge' && frame.expectedAbstention === false &&
      !frame.scene?.occlusions && Number.isInteger(frame.ply) && session.fens[frame.ply] === frame.fen;
    const continues = clean && run && run.session.id === frame.session &&
      (frame.ply === run.frames.at(-1).ply || frame.ply === run.frames.at(-1).ply + 1);
    if (continues) run.frames.push({...frame, position});
    else {
      if (run) runs.push(run);
      run = clean ? {session, frames: [{...frame, position}]} : null;
    }
  });
  if (run) runs.push(run);
  return runs;
}

/** Every ply in a window must be seen on at least two frames so the tracker can stabilize it. */
function trimToStablePlies(frames) {
  const counts = new Map();
  for (const frame of frames) counts.set(frame.ply, (counts.get(frame.ply) ?? 0) + 1);
  let end = frames.length;
  while (end > 0 && counts.get(frames[end - 1].ply) < 2) end--;
  const kept = frames.slice(0, end);
  return kept.every(frame => counts.get(frame.ply) >= 2) ? kept : [];
}

function describeWindow(session, frames) {
  const firstPly = frames[0].ply, lastPly = frames.at(-1).ply;
  const moves = session.moves.slice(firstPly, lastPly);
  const special = [...new Set(moves.flatMap(move => [...move.flags].filter(flag => SPECIAL_FLAGS[flag]).map(flag => SPECIAL_FLAGS[flag])))].sort();
  const distinctBoards = new Set(frames.map(frame => frame.fen.split(' ')[0])).size;
  return {sessionId: session.id, split: session.split, firstPosition: frames[0].position, frameCount: frames.length,
    plies: lastPly - firstPly, specialMoveKinds: special, distinctBoards, moves};
}

export function selectSegment(truth) {
  const windows = [];
  for (const run of candidateRuns(truth)) {
    // Windows start on the first frame of a ply (a full stable pair) and end on a stable pair.
    for (let start = 0; start < run.frames.length; start++) {
      if (start > 0 && run.frames[start - 1].ply === run.frames[start].ply) continue;
      const frames = trimToStablePlies(run.frames.slice(start, start + MAX_FRAMES));
      if (frames.length >= MIN_FRAMES) windows.push({run, frames, summary: describeWindow(run.session, frames)});
    }
  }
  if (!windows.length) fail(`No clean legal segment of ${MIN_FRAMES}-${MAX_FRAMES} frames exists in this corpus.`);
  // Most special-move kinds, then capture present, then most distinct boards, then longest, then corpus order.
  const key = ({summary: s}) => [s.specialMoveKinds.length, s.specialMoveKinds.includes('capture') ? 1 : 0,
    s.distinctBoards, s.frameCount, -s.firstPosition];
  windows.sort((a, b) => { const x = key(a), y = key(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return y[i] - x[i]; return 0; });
  const compact = ({moves, ...rest}) => rest;
  const tooShortWithSpecialMoves = candidateRuns(truth)
    .map(run => describeWindow(run.session, run.frames))
    .filter(summary => summary.frameCount < MIN_FRAMES && summary.specialMoveKinds.length).map(compact);
  return {chosen: windows[0], considered: windows.map(window => compact(window.summary)), tooShortWithSpecialMoves};
}

export function selectInterruption(truth) {
  for (const sessionId of CHALLENGE_PREFERENCE) {
    const position = truth.frames.findIndex(frame => frame.session === sessionId && frame.expectedAbstention === true);
    if (position >= 0) return {...truth.frames[position], position};
  }
  return fail('No challenge/occluded frame with expected abstention exists in this corpus.');
}

async function readCorpus(corpus) {
  const indexBytes = await readFile(join(corpus, 'pixels', 'index.json'));
  const truthBytes = await readFile(join(corpus, 'evaluator', 'truth.json'));
  const index = JSON.parse(indexBytes), truth = JSON.parse(truthBytes);
  if (index.schemaVersion !== 1 || index.mode !== 'synthetic-pixels' || truth.schemaVersion !== 1) fail('Unexpected corpus schema.');
  if (index.frames.length !== truth.frames.length || index.frames.some((frame, i) => frame.id !== truth.frames[i].id || frame.file !== truth.frames[i].file)) {
    fail('Pixel index and evaluator truth are not aligned.');
  }
  return {index, truth, indexSha256: sha256(indexBytes), truthSha256: sha256(truthBytes)};
}

export async function buildReplaySequence({corpus, out}) {
  corpus = resolve(corpus); out = resolve(out);
  if (out === corpus || out.startsWith(corpus + '/')) fail('Output must be outside the read-only corpus.');
  const {truth, indexSha256, truthSha256} = await readCorpus(corpus);
  const {chosen, considered, tooShortWithSpecialMoves} = selectSegment(truth);
  const interruption = selectInterruption(truth);
  const pixelsOut = join(out, 'pixels');
  await mkdir(pixelsOut, {recursive: true});
  const stale = (await readdir(pixelsOut)).filter(name => /^frame-\d{3}\.png$/.test(name));
  const ordered = [...chosen.frames, interruption];
  if (stale.some(name => !ordered.some((_, i) => name === `frame-${String(i).padStart(3, '0')}.png`))) {
    fail('Output pixels directory contains frames from a different selection; use an empty directory.');
  }
  const copies = [];
  for (const [i, frame] of ordered.entries()) {
    const file = `frame-${String(i).padStart(3, '0')}.png`;
    const source = join(corpus, 'pixels', frame.file);
    const bytes = await readFile(source);
    const digest = sha256(bytes);
    if (digest !== frame.sourceSha256) fail(`Corpus frame ${frame.id} does not match its frozen hash.`);
    await copyFile(source, join(pixelsOut, file));
    if (sha256(await readFile(join(pixelsOut, file))) !== digest) fail(`Copy of ${frame.id} is not byte-identical.`);
    copies.push({index: i, file, sha256: digest, timestampMs: i * FRAME_SPACING_MS});
  }
  const main = copies.slice(0, chosen.frames.length), interrupt = copies.at(-1);
  const session = chosen.run.session;
  const firstPly = chosen.frames[0].ply;
  const manifest = {
    schemaVersion: 1,
    kind: 'offline-replay-sequence',
    generator: 'scripts/simulation/select-replay-sequence.mjs',
    source: {corpusIndexSha256: indexSha256, corpusTruthSha256: truthSha256,
      description: 'Byte-for-byte copies of existing synthetic known-template frames; not physical-board images.'},
    frames: main.map(({index, file, sha256, timestampMs}) => ({index, file, sha256, timestampMs})),
    interruption: {file: interrupt.file, sha256: interrupt.sha256, playAfterFrameIndex: main.at(-1).index,
      purpose: 'Unusable frame inserted after the sequence; replay must withhold or revoke tracking.'},
    evaluatorTruth: {
      notice: 'Evaluator/test-fixture data only. A replay player must not feed this to recognition or tracking; the starting state stands in for one explicit human review.',
      sessionId: session.id, split: session.split, startingFen: chosen.frames[0].fen,
      startingStateSource: session.initialStateSource,
      historyKnownFromInitial: session.historyKnownFromInitial && firstPly === 0,
      specialMoveKinds: chosen.summary.specialMoveKinds,
      moves: chosen.summary.moves.map(move => move.san),
      frames: chosen.frames.map((frame, i) => ({index: i, sourceFrameId: frame.id, ply: frame.ply - firstPly,
        moveSan: frame.ply > firstPly ? session.moves[frame.ply - 1].san : null, expectedFen: frame.fen})),
      interruption: {sourceFrameId: interruption.id, challenge: interruption.session,
        expectedAbstention: true, expectedTracking: 'withheld-or-revoked'},
      selection: {rule: `Clean contiguous same-session frames (no challenge/occlusion), ${MIN_FRAMES}-${MAX_FRAMES} frames, every ply seen twice; ranked by special-move kinds, capture, distinct boards, length, corpus order.`,
        corpusHasQualifyingCapture: considered.some(window => window.specialMoveKinds.includes('capture')),
        considered, tooShortWithSpecialMoves}
    }
  };
  const text = JSON.stringify(manifest, null, 2) + '\n';
  await writeFile(join(out, 'replay-manifest.json'), text);
  // Same schema the native conformance runner accepts: opaque ids, files and timestamps only.
  const index = {schemaVersion: 1, mode: 'synthetic-pixels',
    frames: copies.map(({file, timestampMs}) => ({id: file.replace('.png', ''), file, timestampMs}))};
  await writeFile(join(pixelsOut, 'index.json'), JSON.stringify(index, null, 2) + '\n');
  return {manifest, manifestSha256: sha256(text)};
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const args = process.argv.slice(2);
    if (args.length !== 4 || args[0] !== '--corpus' || args[2] !== '--out') {
      fail('Usage: node scripts/simulation/select-replay-sequence.mjs --corpus CORPUS_DIR --out OUTPUT_DIR');
    }
    const {manifest, manifestSha256} = await buildReplaySequence({corpus: args[1], out: args[3]});
    const t = manifest.evaluatorTruth;
    console.log(JSON.stringify({manifestSha256, session: t.sessionId, frames: manifest.frames.length,
      sourceFrames: `${t.frames[0].sourceFrameId}-${t.frames.at(-1).sourceFrameId}`, moves: t.moves,
      specialMoveKinds: t.specialMoveKinds, interruption: t.interruption.sourceFrameId,
      corpusHasQualifyingCapture: t.selection.corpusHasQualifyingCapture}));
  } catch (error) { console.error(`Replay selection failed: ${error.message}`); process.exitCode = 1; }
}
