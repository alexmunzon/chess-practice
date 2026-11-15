#!/usr/bin/env node
// Engine time-budget study (Mac-side evidence only; NOT phone timings).
// Runs the pinned Stockfish 19 single-thread WebAssembly build (the same files the
// phone bundles) in a Node worker, one engine at a time, and measures:
//   ladder:       move quality versus fixed node budgets on a seeded position set;
//   first-search: what a fresh worker's first search pays for, and whether a warm-up helps;
//   positions:    the seeded position list and its sha256 (determinism check).
// Usage:
//   node scripts/engine-budget-report.mjs --out FILE [--positions N --seed S] [--mode ladder|positions|first-search]
// The reference is the same engine searched longer. It is not ground truth.
import {Worker} from 'node:worker_threads';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
import {loadavg} from 'node:os';
import {fileURLToPath} from 'node:url';
import {Chess} from 'chess.js';
import {loadPosition} from '../src/core/position.js';

export const ENGINE_JS = fileURLToPath(new URL('../node_modules/stockfish/bin/stockfish-19-single.js', import.meta.url));
export const ENGINE_WASM = ENGINE_JS.replace(/\.js$/, '.wasm');
export const DEFAULT_SEED = 20261115;
export const DEFAULT_LADDER = [5000, 20000, 50000, 100000, 200000];
export const APP_HASH_MB = 32; // src/core/worker-engine.js
export const APP_MOVETIME_MS = 1000; // native/ChessCompanionApp OfflineStudy.swift and ReplayGame.swift
export const CLAMP_CP = 1000;

// ---------- pure helpers (unit-tested) ----------
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
/** Side-to-move score in centipawns, clamped to +-CLAMP_CP; any mate counts as +-CLAMP_CP. */
export function scoreToCp(score) {
  if (!score) return null;
  if (score.mate !== undefined && score.mate !== null) return score.mate > 0 ? CLAMP_CP : -CLAMP_CP;
  return Math.max(-CLAMP_CP, Math.min(CLAMP_CP, score.cp));
}
/** Evaluation loss of a move versus the reference move, both scored at reference depth. */
export function moveLoss(refScore, moveScore) {
  const raw = scoreToCp(refScore) - scoreToCp(moveScore);
  return {loss: Math.max(0, raw), negative: raw < 0};
}
export function percentile(values, p) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.max(0, Math.ceil(p * sorted.length) - 1)];
}
export const median = values => percentile(values, 0.5);
const PIECE_VALUE = {n: 3, b: 3, r: 5, q: 9};
export function nonPawnMaterial(fen) {
  let total = 0;
  for (const ch of fen.split(' ')[0]) total += PIECE_VALUE[ch.toLowerCase()] || 0;
  return total;
}
export function phaseOf(fen) {
  const npm = nonPawnMaterial(fen), fullmove = Number(fen.split(' ')[5]);
  if (npm <= 20) return 'endgame';
  if (fullmove <= 12 && npm >= 54) return 'opening';
  return 'middlegame';
}
export function positionListSha(positions) {
  return createHash('sha256').update(positions.map(p => p.fen).join('\n') + '\n').digest('hex');
}
export function parseInfo(line) {
  const out = {};
  const num = key => { const m = line.match(new RegExp(`\\b${key} (-?\\d+)`)); return m ? Number(m[1]) : undefined; };
  out.depth = num('depth'); out.seldepth = num('seldepth'); out.multipv = num('multipv') ?? 1;
  out.nodes = num('nodes'); out.nps = num('nps'); out.time = num('time');
  const score = line.match(/\bscore (cp|mate) (-?\d+)/);
  if (score) out.score = score[1] === 'cp' ? {cp: Number(score[2])} : {mate: Number(score[2])};
  out.bound = /\b(lowerbound|upperbound)\b/.test(line);
  const pv = line.match(/\bpv (.+)$/);
  out.pv = pv ? pv[1].trim().split(/\s+/) : [];
  return out;
}

// ---------- hand-written tactical positions ----------
// Each has one intended winning move. Kept only if the deep reference search agrees
// (and, with MultiPV 2, the second-best move is clearly worse); see verifyTactics().
export const TACTICS = [
  {id: 'back-rank-m1', fen: '6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1', best: 'd1d8', theme: 'mate in 1'},
  {id: 'scholars-m1', fen: 'r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4', best: 'f3f7', theme: 'mate in 1'},
  {id: 'fools-m1', fen: 'rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq g3 0 2', best: 'd8h4', theme: 'mate in 1'},
  {id: 'smothered-m1', fen: '6rk/6pp/8/6N1/8/8/8/6K1 w - - 0 1', best: 'g5f7', theme: 'mate in 1'},
  {id: 'queen-corner-m1', fen: 'k7/8/1K6/8/8/8/7Q/8 w - - 0 1', best: 'h2h8', theme: 'mate in 1'},
  {id: 'rook-roller-m1', fen: '7k/R7/8/8/8/8/8/1R4K1 w - - 0 1', best: 'b1b8', theme: 'mate in 1'},
  {id: 'black-rook-roller-m1', fen: '1r4k1/8/8/8/8/8/r7/7K b - - 0 1', best: 'b8b1', theme: 'mate in 1'},
  {id: 'black-back-rank-m1', fen: '3r2k1/5ppp/8/8/8/8/5PPP/6K1 b - - 0 1', best: 'd8d1', theme: 'mate in 1'},
  {id: 'doubled-rooks-m2', fen: 'r5k1/5ppp/8/8/8/8/3R1PPP/3R2K1 w - - 0 1', best: 'd2d8', theme: 'mate in 2'},
  {id: 'black-doubled-rooks-m2', fen: '3r2k1/3r1ppp/8/8/8/8/5PPP/R5K1 b - - 0 1', best: 'd7d1', theme: 'mate in 2'},
  {id: 'free-queen-rook', fen: '4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1', best: 'd2d5', theme: 'hanging queen'},
  {id: 'black-free-queen', fen: '3rk3/8/8/8/3Q4/8/8/4K3 b - - 0 1', best: 'd8d4', theme: 'hanging queen'},
  {id: 'knight-takes-queen', fen: '4k3/5ppp/8/8/8/2n5/5PPP/3QK3 b - - 0 1', best: 'c3d1', theme: 'queen capture'},
  {id: 'free-rook', fen: '4k3/8/8/8/8/8/r7/R3K3 w - - 0 1', best: 'a1a2', theme: 'hanging rook'},
  {id: 'knight-fork-queen', fen: '4k3/1q3ppp/8/8/2N5/8/5PPP/4K3 w - - 0 1', best: 'c4d6', theme: 'knight fork'},
  {id: 'knight-fork-rook', fen: '2r3k1/5ppp/8/3N4/8/8/5PPP/6K1 w - - 0 1', best: 'd5e7', theme: 'knight fork'},
  {id: 'black-knight-fork', fen: '6k1/5ppp/8/8/3n4/8/5PPP/R3K3 b - - 0 1', best: 'd4c2', theme: 'knight fork'},
  {id: 'philidor-smothered', fen: 'r6k/6pp/8/6N1/2Q5/8/1q6/6K1 w - - 0 1', best: 'g5f7', theme: 'smothered mate in 4 (queen sacrifice)'},
  {id: 'promote-queen', fen: '8/1P6/8/8/8/8/k7/4K3 w - - 0 1', best: 'b7b8q', theme: 'promotion'},
];

// ---------- engine harness ----------
const WORKER_SRC = `
const {parentPort, workerData} = require('node:worker_threads');
const t0 = performance.now();
const createEngine = require(workerData.enginePath);
const t1 = performance.now();
const engine = createEngine();
const t2 = performance.now();
engine.listener = line => parentPort.postMessage(line);
parentPort.postMessage('__timing require ' + (t1 - t0).toFixed(1) + ' create ' + (t2 - t1).toFixed(1));
parentPort.on('message', c => engine.processCommand(c));
`;

export class Engine {
  constructor() { this.waiters = []; this.lines = []; this.startupLines = []; this.multipv = 1; }
  async start({hash = APP_HASH_MB} = {}) {
    const t = {created: performance.now()};
    this.worker = new Worker(WORKER_SRC, {eval: true, workerData: {enginePath: ENGINE_JS}});
    this.worker.on('message', msg => {
      for (const line of String(msg).split('\n')) {
        const text = line.trim();
        if (!text) continue;
        if (this.collectStartup) this.startupLines.push({ms: performance.now() - t.created, text});
        this.lines.push(text);
        for (const w of [...this.waiters]) if (w.test(text)) { this.waiters.splice(this.waiters.indexOf(w), 1); w.resolve(text); }
      }
    });
    this.worker.on('error', e => { for (const w of this.waiters) w.reject(e); this.waiters = []; });
    this.collectStartup = true;
    this.send('uci');
    await this.wait(l => l === 'uciok');
    t.uciok = performance.now();
    this.send(`setoption name Hash value ${hash}`);
    this.send('isready');
    await this.wait(l => l === 'readyok');
    t.readyok = performance.now();
    this.collectStartup = false;
    return {toUciokMs: t.uciok - t.created, uciokToReadyMs: t.readyok - t.uciok, toReadyMs: t.readyok - t.created};
  }
  send(cmd) { this.worker.postMessage(cmd); }
  wait(test, timeoutMs = 120000) {
    return new Promise((resolve, reject) => {
      const w = {test, resolve, reject};
      this.waiters.push(w);
      setTimeout(() => { if (this.waiters.includes(w)) { this.waiters.splice(this.waiters.indexOf(w), 1); reject(new Error('engine timeout')); } }, timeoutMs).unref();
    });
  }
  async newGame() { this.send('ucinewgame'); this.send('isready'); await this.wait(l => l === 'readyok'); }
  /** One search. limit: {nodes} | {movetime}. Returns best move, last unbounded multipv-1 info, wall time. */
  async search(fen, {nodes, depth, movetime, searchmoves, multipv = 1, clear = true, moves} = {}) {
    if (clear) await this.newGame();
    if (multipv !== this.multipv) { this.send(`setoption name MultiPV value ${multipv}`); this.multipv = multipv; await this.newGame(); }
    this.send(`position fen ${fen}${moves?.length ? ' moves ' + moves.join(' ') : ''}`);
    this.lines = [];
    const go = 'go' + (depth ? ` depth ${depth}` : '') + (nodes ? ` nodes ${nodes}` : '') + (movetime ? ` movetime ${movetime}` : '') + (searchmoves?.length ? ` searchmoves ${searchmoves.join(' ')}` : '');
    const start = performance.now();
    this.send(go);
    const bestLine = await this.wait(l => l.startsWith('bestmove'));
    const wallMs = performance.now() - start;
    const infos = this.lines.filter(l => l.startsWith('info ') && /\bscore /.test(l)).map(parseInfo);
    const byPv = {};
    for (const info of infos) if (!info.bound || !byPv[info.multipv]) byPv[info.multipv] = info;
    const main = byPv[1] || infos.at(-1) || {};
    const last = infos.at(-1) || {};
    return {bestmove: bestLine.split(/\s+/)[1], depth: main.depth, seldepth: main.seldepth, score: main.score,
      nodes: last.nodes, time: last.time, nps: last.nps, wallMs, lines: Object.values(byPv)};
  }
  async quit() { try { this.send('quit'); } catch {} await this.worker?.terminate(); }
}

// ---------- seeded position set ----------
export async function generatePositions(engine, {count = 102, seed = DEFAULT_SEED, maxGames = 200, maxPlies = 160, log = () => {}} = {}) {
  const rng = mulberry32(seed);
  const target = {opening: Math.round(count * 0.3), endgame: Math.round(count * 0.3)};
  target.middlegame = count - target.opening - target.endgame;
  const picked = {opening: [], middlegame: [], endgame: []};
  const seen = new Set();
  const perGame = {opening: 1, middlegame: 2, endgame: 2};
  let games = 0;
  const full = () => Object.keys(target).every(k => picked[k].length >= target[k]);
  while (!full() && games < maxGames) {
    games++;
    const chess = new Chess();
    const randomPlies = 2 + Math.floor(rng() * 4);
    const gameNodes = 800 + Math.floor(rng() * 1200);
    const cands = {opening: [], middlegame: [], endgame: []};
    await engine.newGame();
    for (let ply = 0; ply < maxPlies && !chess.isGameOver(); ply++) {
      let uci;
      if (ply < randomPlies || rng() < 0.05) {
        const moves = chess.moves({verbose: true});
        const m = moves[Math.floor(rng() * moves.length)];
        uci = m.from + m.to + (m.promotion || '');
      } else {
        const fen = chess.fen();
        const r = await engine.search(fen, {nodes: gameNodes, clear: false});
        uci = r.bestmove;
        // Candidate only if the side to move is not already decided (no mate score, |eval| <= 600 cp
        // at the generation budget), so the set tests decisions rather than trivially won positions.
        if (ply >= 8 && r.score && r.score.mate === undefined && Math.abs(r.score.cp) <= 600) cands[phaseOf(fen)].push(fen);
      }
      chess.move({from: uci.slice(0, 2), to: uci.slice(2, 4), ...(uci[4] ? {promotion: uci[4]} : {})});
    }
    for (const phase of Object.keys(cands)) {
      let take = Math.min(perGame[phase], target[phase] - picked[phase].length);
      const pool = cands[phase].filter(f => !seen.has(f.split(' ').slice(0, 4).join(' ')));
      while (take > 0 && pool.length) {
        const fen = pool.splice(Math.floor(rng() * pool.length), 1)[0];
        const key = fen.split(' ').slice(0, 4).join(' ');
        if (seen.has(key)) continue;
        loadPosition(fen); // same validation the app applies
        seen.add(key); picked[phase].push({id: `${phase}-${String(picked[phase].length + 1).padStart(3, '0')}`, fen, phase, source: `seed ${seed} game ${games}`});
        take--;
      }
    }
    log(`game ${games}: opening ${picked.opening.length}/${target.opening} middlegame ${picked.middlegame.length}/${target.middlegame} endgame ${picked.endgame.length}/${target.endgame}`);
  }
  return {positions: [...picked.opening, ...picked.middlegame, ...picked.endgame], games, target};
}

// ---------- ladder ----------
export async function verifyTactics(engine, refNodes) {
  const out = [];
  for (const t of TACTICS) {
    loadPosition(t.fen);
    const r = await engine.search(t.fen, {nodes: refNodes, multipv: 2});
    const first = r.lines.find(l => l.multipv === 1), second = r.lines.find(l => l.multipv === 2);
    const gap = second ? scoreToCp(first.score) - scoreToCp(second.score) : Infinity;
    const firstMove = first?.pv?.[0] ?? r.bestmove;
    // A second mate is still "clearly worse" only if it is slower; accept mate-vs-mate when longer.
    const mateSlower = first?.score?.mate > 0 && second?.score?.mate > 0 && second.score.mate > first.score.mate;
    out.push({...t, refMove: r.bestmove, refScore: first?.score, secondMove: second?.pv?.[0], secondScore: second?.score,
      gapCp: Number.isFinite(gap) ? gap : null, verified: r.bestmove === t.best && firstMove === t.best && (gap >= 150 || mateSlower)});
  }
  return out;
}

export async function runLadder({count, seed, refNodes, altCap = refNodes, ladder, appMovetime, log}) {
  const engine = new Engine();
  const startup = await engine.start();
  const t0 = performance.now();
  const gen = await generatePositions(engine, {count, seed, log});
  const genMs = performance.now() - t0;
  log(`positions: ${gen.positions.length} from ${gen.games} games in ${(genMs / 1000).toFixed(1)} s; sha256 ${positionListSha(gen.positions)}`);
  const tactics = await verifyTactics(engine, refNodes);
  log(`tactics verified: ${tactics.filter(t => t.verified).length}/${tactics.length}`);
  const set = [...gen.positions, ...tactics.filter(t => t.verified).map(t => ({id: t.id, fen: t.fen, phase: 'tactical', solution: t.best, theme: t.theme}))];
  const rows = [];
  const tLadder = performance.now();
  for (const [i, pos] of set.entries()) {
    const budgets = {};
    for (const n of ladder) budgets[n] = await engine.search(pos.fen, {nodes: n});
    if (appMovetime) budgets[`movetime${appMovetime}`] = await engine.search(pos.fen, {movetime: appMovetime});
    // Reference last, so its hash table is still warm for the alternative-move evaluations.
    const ref = await engine.search(pos.fen, {nodes: refNodes});
    const evalCache = {[ref.bestmove]: ref.score};
    let altNodes = 0;
    for (const b of Object.values(budgets)) {
      if (b.bestmove in evalCache) continue;
      // Reference-DEPTH evaluation of the budget's move: same nominal depth as the reference,
      // warm hash from the reference search, capped at altCap nodes.
      const alt = await engine.search(pos.fen, {depth: ref.depth, nodes: altCap, searchmoves: [b.bestmove], clear: false});
      evalCache[b.bestmove] = alt.score; altNodes += alt.nodes || 0;
    }
    const row = {id: pos.id, phase: pos.phase, fen: pos.fen, solution: pos.solution ?? null,
      ref: {move: ref.bestmove, score: ref.score, depth: ref.depth, nodes: ref.nodes, wallMs: Math.round(ref.wallMs)}, altEvalNodes: altNodes, budgets: {}};
    for (const [k, b] of Object.entries(budgets)) {
      const {loss, negative} = moveLoss(ref.score, evalCache[b.bestmove]);
      row.budgets[k] = {move: b.bestmove, same: b.bestmove === ref.bestmove, lossCp: loss, negativeRaw: negative,
        refDepthScore: evalCache[b.bestmove], depth: b.depth, nodes: b.nodes, wallMs: Math.round(b.wallMs), engineMs: b.time,
        solved: pos.solution ? b.bestmove === pos.solution : null};
    }
    rows.push(row);
    if ((i + 1) % 10 === 0 || i === set.length - 1) log(`ladder ${i + 1}/${set.length} (${((performance.now() - tLadder) / 1000).toFixed(0)} s)`);
  }
  await engine.quit();
  return {startup, generation: {games: gen.games, target: gen.target, ms: Math.round(genMs), sha256: positionListSha(gen.positions)},
    positions: gen.positions, tactics, rows, ladderMs: Math.round(performance.now() - tLadder)};
}

export function summarize(rows, keys) {
  const table = [];
  for (const k of keys) {
    const b = rows.map(r => r.budgets[k]).filter(Boolean);
    const losses = b.map(x => x.lossCp);
    const tactical = rows.filter(r => r.solution && r.budgets[k]);
    const nodes = b.reduce((s, x) => s + (x.nodes || 0), 0), ms = b.reduce((s, x) => s + (x.engineMs || 0), 0);
    table.push({budget: k, n: b.length,
      sameAsRef: b.filter(x => x.same).length / b.length,
      meanLossCp: losses.reduce((s, x) => s + x, 0) / b.length,
      p95LossCp: percentile(losses, 0.95),
      over100: b.filter(x => x.lossCp > 100).length / b.length,
      over300: b.filter(x => x.lossCp > 300).length / b.length,
      tacticalSolved: `${tactical.filter(r => r.budgets[k].solved).length}/${tactical.length}`,
      medianDepth: median(b.map(x => x.depth || 0)),
      medianNodes: median(b.map(x => x.nodes || 0)),
      medianWallMs: median(b.map(x => x.wallMs)),
      macNps: ms ? Math.round(nodes / ms * 1000) : null,
      negativeLossShare: b.filter(x => x.negativeRaw).length / b.length});
  }
  return table;
}

export function markdownTable(table) {
  const pct = x => (100 * x).toFixed(1) + '%';
  const lines = ['| budget | same move as ref | mean loss cp | p95 loss cp | loss>100 | loss>300 | tactics solved | median depth | median nodes | median Mac ms | Mac nps |',
    '|---|---|---|---|---|---|---|---|---|---|---|'];
  for (const r of table) lines.push(`| ${r.budget} | ${pct(r.sameAsRef)} | ${r.meanLossCp.toFixed(1)} | ${r.p95LossCp} | ${pct(r.over100)} | ${pct(r.over300)} | ${r.tacticalSolved} | ${r.medianDepth} | ${r.medianNodes} | ${r.medianWallMs} | ${r.macNps} |`);
  return lines.join('\n');
}

// ---------- first-search experiment ----------
const FIRST_SEARCH_FEN = 'r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N2N2/PP2BPPP/R2QKB1R w KQ - 0 8';
export async function firstSearchRun({reps = 10, nodes = 300000, warmup = false, warmupNodes = 5000, searches = 5, log}) {
  const runs = [];
  for (let rep = 0; rep < reps; rep++) {
    const engine = new Engine();
    const startup = await engine.start();
    let warm = null;
    if (warmup) {
      const w = await engine.search('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', {nodes: warmupNodes});
      warm = {wallMs: w.wallMs, nodes: w.nodes};
    }
    const list = [];
    for (let s = 0; s < searches; s++) {
      const r = await engine.search(FIRST_SEARCH_FEN, {nodes});
      list.push({wallMs: r.wallMs, engineMs: r.time, nodes: r.nodes, nps: r.nps, depth: r.depth, move: r.bestmove});
    }
    runs.push({loadAvg1m: loadavg()[0], startup, warm, searches: list, startupLines: rep === 0 ? engine.startupLines.map(l => ({ms: Math.round(l.ms), text: l.text.slice(0, 160)})) : undefined});
    await engine.quit();
    log?.(`rep ${rep + 1}/${reps}: ready ${startup.toReadyMs.toFixed(0)} ms, searches ${list.map(x => x.wallMs.toFixed(0)).join('/')} ms`);
  }
  // Standalone compile timing of the same 99 MB module in this process.
  const t0 = performance.now(); const bytes = readFileSync(ENGINE_WASM); const t1 = performance.now();
  await WebAssembly.compile(bytes); const t2 = performance.now();
  return {nodes, warmup, warmupNodes: warmup ? warmupNodes : 0, execArgv: process.execArgv, runs,
    wasm: {bytes: bytes.length, readMs: t1 - t0, compileMs: t2 - t1}, summary: summarizeFirst(runs)};
}
export function summarizeFirst(runs) {
  const at = i => runs.map(r => r.searches[i]);
  const s = {toReadyMsMedian: median(runs.map(r => r.startup.toReadyMs)), toUciokMsMedian: median(runs.map(r => r.startup.toUciokMs)),
    uciokToReadyMsMedian: median(runs.map(r => r.startup.uciokToReadyMs)), perSearch: []};
  for (let i = 0; i < runs[0].searches.length; i++) {
    const xs = at(i);
    s.perSearch.push({search: i + 1, medianWallMs: median(xs.map(x => x.wallMs)), maxWallMs: Math.max(...xs.map(x => x.wallMs)),
      medianNps: median(xs.map(x => x.nps)), sameNodesAsSearch2: xs.every((x, k) => x.nodes === runs[k].searches[Math.min(1, runs[k].searches.length - 1)].nodes)});
  }
  const later = runs.flatMap(r => r.searches.slice(1).map(x => x.wallMs));
  s.firstOverLaterMedian = s.perSearch[0].medianWallMs / median(later);
  // Same-worker ratio per rep: insensitive to slow drifts in machine load between reps.
  s.perRepFirstOverLater = runs.map(r => r.searches[0].wallMs / median(r.searches.slice(1).map(x => x.wallMs)));
  s.medianPerRepRatio = median(s.perRepFirstOverLater);
  s.loadAvg1m = runs.map(r => r.loadAvg1m);
  if (runs[0].warm) s.warmupMedianWallMs = median(runs.map(r => r.warm.wallMs));
  return s;
}

function runChild(flags, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [...flags, fileURLToPath(import.meta.url), ...args], {stdio: ['ignore', 'pipe', 'inherit']});
    let out = ''; child.stdout.on('data', d => { out += d; });
    child.on('exit', code => code === 0 ? resolve(JSON.parse(out)) : reject(new Error(`child exit ${code}`)));
  });
}

// ---------- CLI ----------
function parseArgs(argv) {
  const a = {mode: 'ladder', positions: 102, seed: DEFAULT_SEED, refNodes: 800000, altCap: 400000, ladder: DEFAULT_LADDER, appMovetime: 0, reps: 10, fsNodes: 100000};
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i], v = argv[i + 1];
    if (k === '--out') { a.out = v; i++; } else if (k === '--positions') { a.positions = Number(v); i++; }
    else if (k === '--seed') { a.seed = Number(v); i++; } else if (k === '--mode') { a.mode = v; i++; }
    else if (k === '--ref-nodes') { a.refNodes = Number(v); i++; } else if (k === '--alt-cap') { a.altCap = Number(v); i++; } else if (k === '--ladder') { a.ladder = v.split(',').map(Number); i++; }
    else if (k === '--app-movetime') { a.appMovetime = Number(v); i++; } else if (k === '--reps') { a.reps = Number(v); i++; }
    else if (k === '--fs-nodes') { a.fsNodes = Number(v); i++; } else if (k === '--warmup') { a.warmup = true; }
    else throw new Error(`unknown argument ${k}`);
  }
  return a;
}
const write = (file, data) => { mkdirSync(dirname(file), {recursive: true}); writeFileSync(file, typeof data === 'string' ? data : JSON.stringify(data, null, 1)); };

async function main() {
  const a = parseArgs(process.argv.slice(2));
  const log = msg => process.stderr.write(`[engine-budget] ${msg}\n`);
  const meta = {engine: 'stockfish 19.0.1 stockfish-19-single (WASM, 1 thread)', hashMb: APP_HASH_MB, node: process.version,
    machine: 'Mac (shared, loaded machine; wall-clock is NOT phone time)', seed: a.seed, date: new Date().toISOString()};
  if (a.mode === 'positions') {
    const engine = new Engine(); await engine.start();
    const gen = await generatePositions(engine, {count: a.positions, seed: a.seed});
    await engine.quit();
    const result = {meta, sha256: positionListSha(gen.positions), games: gen.games, positions: gen.positions};
    if (a.out) write(a.out, result);
    process.stdout.write(`positions ${gen.positions.length} sha256 ${result.sha256}\n`);
    return;
  }
  if (a.mode === 'first-search-child') {
    process.stdout.write(JSON.stringify(await firstSearchRun({reps: a.reps, nodes: a.fsNodes, warmup: !!a.warmup, log})));
    return;
  }
  if (a.mode === 'first-search') {
    const variants = [
      {label: 'default (cold)', flags: [], warmup: false},
      {label: 'default + 5k-node warm-up', flags: [], warmup: true},
      {label: '--no-liftoff (optimizing compiler up front)', flags: ['--no-liftoff'], warmup: false},
      {label: '--liftoff-only (never tier up)', flags: ['--liftoff-only'], warmup: false},
    ];
    const results = [];
    for (const v of variants) {
      log(`variant ${v.label}`);
      const args = ['--mode', 'first-search-child', '--reps', String(a.reps), '--fs-nodes', String(a.fsNodes), ...(v.warmup ? ['--warmup'] : [])];
      results.push({label: v.label, ...(await runChild(v.flags, args))});
    }
    const result = {meta, fen: FIRST_SEARCH_FEN, results};
    if (a.out) write(a.out, result);
    for (const r of results) process.stdout.write(`${r.label}: ready ${r.summary.toReadyMsMedian.toFixed(0)} ms (uciok ${r.summary.toUciokMsMedian.toFixed(0)}), compile-alone ${r.wasm.compileMs.toFixed(0)} ms; search wall ms median 1..5 = ${r.summary.perSearch.map(p => p.medianWallMs.toFixed(0)).join(' / ')}; first/later (per-worker median) ${r.summary.medianPerRepRatio.toFixed(2)}; load ${Math.min(...r.summary.loadAvg1m).toFixed(0)}-${Math.max(...r.summary.loadAvg1m).toFixed(0)}${r.summary.warmupMedianWallMs ? `; warm-up ${r.summary.warmupMedianWallMs.toFixed(0)} ms` : ''}\n`);
    return;
  }
  if (!a.out) throw new Error('--out FILE is required');
  const res = await runLadder({count: a.positions, seed: a.seed, refNodes: a.refNodes, altCap: a.altCap, ladder: a.ladder, appMovetime: a.appMovetime, log});
  const keys = [...a.ladder.map(String), ...(a.appMovetime ? [`movetime${a.appMovetime}`] : [])];
  const all = summarize(res.rows, keys);
  const byPhase = Object.fromEntries(['opening', 'middlegame', 'endgame', 'tactical'].map(p => [p, summarize(res.rows.filter(r => r.phase === p), keys)]));
  const refSummary = {nodes: a.refNodes, medianDepth: median(res.rows.map(r => r.ref.depth)), medianWallMs: median(res.rows.map(r => r.ref.wallMs))};
  write(a.out, {meta: {...meta, refNodes: a.refNodes, altCapNodes: a.altCap, ladder: a.ladder, appMovetimeMs: a.appMovetime}, ...res, summary: all, byPhase, refSummary});
  const md = `${markdownTable(all)}\n\nReference: ${a.refNodes} nodes, median depth ${refSummary.medianDepth}, median Mac ${refSummary.medianWallMs} ms. Positions sha256 ${res.generation.sha256}.\n` +
    Object.entries(byPhase).map(([p, t]) => `\n### ${p}\n${markdownTable(t)}`).join('\n');
  write(a.out.replace(/\.json$/, '') + '.md', md);
  process.stdout.write(md + '\n');
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().catch(e => { process.stderr.write(`${e.stack || e}\n`); process.exit(1); });
}
