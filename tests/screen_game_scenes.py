#!/usr/bin/env python3
"""Checks the SIMULATED screen-game scenes and their answer keys (truth/games.json) in BOTH roots:
round one `scenes/` (smoke, dev, heldout; each position once, ~10% repeats) and round two
`scenes-v2/` (smoke2, dev2, heldout2; every position shown 3 times: 1 + 2 repeats).

Run: python3 -B tests/screen_game_scenes.py [--skip-determinism]
Determinism runs use 2 worker processes under `nice -n 10`.
"""
import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / 'scripts/recognition/make_screen_game_scenes.py'
LINES = ROOT / 'scripts/recognition/make-game-lines.mjs'
START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
BUILD = Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15')
V1, V2 = BUILD / 'scenes', BUILD / 'scenes-v2'
PER_POSITION = 2
SKIP_DET = False
FLAGS = {'capture', 'enpassant', 'castle-k', 'castle-q', 'promotion', 'check'}


def load(root):
    return json.loads((root / 'truth' / 'games.json').read_text())


def base_split(name):
    return name.rstrip('0123456789')


def fit_h(src, dst):
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u*x, -u*y, -u])
        rows.append([0, 0, 0, x, y, 1, -v*x, -v*y, -v])
    h = np.linalg.svd(np.asarray(rows, float))[2][-1].reshape(3, 3)
    return h / h[2, 2]


def board_h(corners):
    """Homography: chess board index coords (a8 square top-left, pixel centres at integers, 512 px) -> image."""
    return fit_h([(-0.5, -0.5), (511.5, -0.5), (511.5, 511.5), (-0.5, 511.5)], corners)


def to_board(corners, xy):
    """Image point -> chess-board unit coords (a8 corner (0,0), h1 corner (1,1))."""
    h = np.linalg.inv(fit_h([(0, 0), (1, 0), (1, 1), (0, 1)], corners))
    p = h @ np.array([xy[0], xy[1], 1.0])
    return p[:2] / p[2]


# Patch inside every piece silhouette (64-px tile coords x 29..35, y 34..42).
_PX, _PY = np.meshgrid(np.arange(29, 36), np.arange(34, 43))


def square_means(img, corners):
    h = board_h(corners)
    means = np.zeros((8, 8, 3))
    for r in range(8):
        for c in range(8):
            pts = np.c_[(c*64 + _PX).ravel(), (r*64 + _PY).ravel(), np.ones(_PX.size)] @ h.T
            x, y = np.rint(pts[:, 0] / pts[:, 2]).astype(int), np.rint(pts[:, 1] / pts[:, 2]).astype(int)
            means[r, c] = img[np.clip(y, 0, img.shape[0]-1), np.clip(x, 0, img.shape[1]-1)].mean(0)
    return means


def occupancy(fen):
    occ = np.zeros((8, 8), bool)
    for r, row in enumerate(fen.split()[0].split('/')):
        c = 0
        for s in row:
            if s.isdigit():
                c += int(s)
            else:
                occ[r, c] = True
                c += 1
    return occ


def separation(means, occ):
    """Gap between the closest occupied square and the farthest empty square, measured as RGB distance
    from the median empty colour of the same square shade. Positive = occupancy separable."""
    shade = (np.add.outer(np.arange(8), np.arange(8)) % 2).astype(bool)
    dist = np.zeros((8, 8))
    for s in (False, True):
        ref = np.median(means[(~occ) & (shade == s)], 0)
        dist[shade == s] = np.linalg.norm(means[shade == s] - ref, axis=1)
    return dist[occ].min() - dist[~occ].max(), dist[occ].min()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate(out, extra):
    run = subprocess.run(['nice', '-n', '10', sys.executable, '-B', str(GEN), '--workers', '2', '--out', str(out)]
                         + extra, capture_output=True, text=True, timeout=1200)
    if run.returncode != 0:
        raise AssertionError(run.stderr)


def subset_bytes(doc, split):
    d = dict(doc)
    d['games'] = [g for g in doc['games'] if g['split'] == split]
    return json.dumps(d, indent=1).encode()


class SceneRootChecks:
    """Mixed into one TestCase per root. Subclasses set ROOT_DIR and V2_MODE."""
    ROOT_DIR = None
    V2_MODE = False

    @classmethod
    def setUpClass(cls):
        cls.doc = load(cls.ROOT_DIR)
        cls.games = cls.doc['games']
        cls.by_split = {}
        for g in cls.games:
            cls.by_split.setdefault(base_split(g['split']), []).append(g)
        cls.sfx = '2' if cls.V2_MODE else ''

    def test_schema(self):
        d = self.doc
        self.assertEqual(d['schema'], 'screen-game-truth-v1')
        self.assertEqual(d['frameSize'], [1920, 1080])
        self.assertTrue(d['cornerOrder'].startswith('a8,h8,h1,a1'))
        game_keys = {'id', 'split', 'seed', 'difficulty', 'cameraMode', 'whiteAtBottom', 'startFen', 'frames'}
        frame_keys = {'index', 'file', 'kind', 'fen', 'moveUci', 'moveSan', 'flags', 'corners', 'disturbance', 'scene'}
        if self.V2_MODE:
            frame_keys |= {'positionIndex'}
        self.assertEqual({g['split'] for g in self.games}, {s + self.sfx for s in ('smoke', 'dev', 'heldout')})
        for g in self.games:
            self.assertTrue(game_keys <= set(g), g['id'])
            self.assertIn(g['difficulty'], ('easy', 'medium', 'hard'))
            self.assertIn(g['cameraMode'], ('fixed', 'jitter', 'drift'))
            self.assertIsInstance(g['whiteAtBottom'], bool)
            self.assertIsInstance(g['seed'], int)
            self.assertEqual(len(g['startFen'].split()), 6)
            for i, f in enumerate(g['frames']):
                self.assertTrue(frame_keys <= set(f), (g['id'], i))
                self.assertEqual(f['index'], i)
                self.assertEqual(f['file'], f'games/{g["id"]}/{i:03d}.png')
                self.assertEqual(len(f['fen'].split()), 6)
                self.assertEqual(np.asarray(f['corners']).shape, (4, 2))
                want = {'glare', 'hand', 'banding'} | ({'sticky'} if self.V2_MODE else set())
                self.assertEqual(set(f['disturbance']), want)
                self.assertTrue(set(f['flags']) <= FLAGS)
                self.assertIsInstance(f['scene'], dict)

    def test_files_exist_and_size(self):
        for g in self.games:
            for f in g['frames']:
                with Image.open(self.ROOT_DIR / f['file']) as im:
                    self.assertEqual(im.size, (1920, 1080), f['file'])

    def test_sequence_and_legality(self):
        checks = []
        for g in self.games:
            fr = g['frames']
            self.assertEqual(fr[0]['kind'], 'start')
            self.assertEqual(fr[0]['fen'], g['startFen'])
            self.assertFalse(fr[0]['disturbance']['glare'] or fr[0]['disturbance']['hand'], g['id'])
            for prev, f in zip(fr, fr[1:]):
                self.assertIn(f['kind'], ('move', 'repeat'))
                if f['kind'] == 'repeat':
                    self.assertEqual(f['fen'], prev['fen'])
                    self.assertIsNone(f['moveUci']); self.assertIsNone(f['moveSan']); self.assertEqual(f['flags'], [])
                else:
                    checks.append({'before': prev['fen'], 'uci': f['moveUci'], 'after': f['fen'], 'san': f['moveSan']})
                    san = f['moveSan']
                    self.assertEqual('castle-k' in f['flags'], san.startswith('O-O') and not san.startswith('O-O-O'))
                    self.assertEqual('castle-q' in f['flags'], san.startswith('O-O-O'))
                    self.assertEqual('promotion' in f['flags'], '=' in san)
                    self.assertEqual('check' in f['flags'], san[-1] in '+#')
                    self.assertEqual('capture' in f['flags'], 'x' in san)
        run = subprocess.run(['node', str(LINES), 'verify'], input=json.dumps({'checks': checks}),
                             capture_output=True, text=True, cwd=ROOT, timeout=300)
        self.assertEqual(run.returncode, 0, run.stderr)
        res = json.loads(run.stdout)
        print(f'  [{self.ROOT_DIR.name}] chess.js verified {res["checked"]} moves, failures {len(res["failures"])}')
        self.assertTrue(res['ok'], res['failures'][:5])

    def positions(self, g):
        """Frames grouped by position (v2: by positionIndex; v1: a move/start frame plus its repeats)."""
        groups = []
        for f in g['frames']:
            if f['kind'] in ('start', 'move'):
                groups.append([f])
            else:
                groups[-1].append(f)
        return groups

    def test_split_content(self):
        s = self.by_split
        self.assertEqual(len(s['smoke']), 2)
        for g in s['smoke']:
            self.assertEqual((g['difficulty'], g['cameraMode']), ('easy', 'fixed'))
            self.assertTrue(6 <= len(self.positions(g)) <= 10)
        for split in ('dev', 'heldout'):
            gs = s[split]
            self.assertEqual(len(gs), 12)
            for d in ('easy', 'medium', 'hard'):
                self.assertEqual(sum(g['difficulty'] == d for g in gs), 4)
                self.assertEqual({g['cameraMode'] for g in gs if g['difficulty'] == d}, {'fixed', 'jitter', 'drift'})
            self.assertGreaterEqual(sum(not g['whiteAtBottom'] for g in gs), 3)
            self.assertLessEqual(sum(g['startFen'] != START for g in gs), 2)
            frames = [f for g in gs for f in g['frames']]
            for g in gs:
                if self.V2_MODE:
                    self.assertTrue(25 <= len(self.positions(g)) <= 35, (g['id'], len(self.positions(g))))
                else:
                    self.assertTrue(30 <= len(g['frames']) <= 45, (g['id'], len(g['frames'])))
            if not self.V2_MODE:
                reps = sum(f['kind'] == 'repeat' for f in frames)
                self.assertTrue(0.06 <= reps / len(frames) <= 0.14, reps / len(frames))
            moves = [f for f in frames if f['kind'] == 'move']
            count = lambda flag: sum(flag in f['flags'] for f in moves)
            self.assertGreaterEqual(count('castle-k'), 2)
            self.assertGreaterEqual(count('castle-q'), 1)
            self.assertGreaterEqual(count('enpassant'), 1)
            self.assertGreaterEqual(count('promotion'), 2)
            self.assertGreaterEqual(sum('promotion' in f['flags'] and f['moveUci'][-1] != 'q' for f in moves), 1)
            self.assertGreaterEqual(count('capture'), 20)
            self.assertEqual(len({tuple(f['moveUci'] for f in g['frames'] if f['kind'] == 'move') for g in gs}), 12)
            mh = [f for g in gs if g['difficulty'] != 'easy' for f in g['frames']]
            occluded = [f for f in mh if f['disturbance']['glare'] or f['disturbance']['hand']]
            self.assertGreater(len(occluded), 0)
            self.assertLess(len(occluded) / len(mh), 0.5)
            self.assertFalse(any(f['disturbance'][k] for g in gs if g['difficulty'] == 'easy'
                                 for f in g['frames'] for k in ('glare', 'hand', 'banding')))
        self.assertFalse({g['seed'] for g in s['dev']} & {g['seed'] for g in s['heldout']})

    def test_camera_modes(self):
        for g in self.games:
            c = np.asarray([f['corners'] for f in g['frames']], float)
            bw = (c[0, :, 0].max() - c[0, :, 0].min())
            shift = np.abs(c - c[0]).max(axis=(1, 2)) / bw
            step = np.abs(np.diff(c, axis=0)).max() / bw if len(c) > 1 else 0
            inside = (c >= 0).all() and (c[..., 0] <= 1919).all() and (c[..., 1] <= 1079).all()
            self.assertTrue(inside, g['id'])
            if g['cameraMode'] == 'fixed':
                self.assertEqual(shift.max(), 0.0, g['id'])
            elif g['cameraMode'] == 'jitter':
                self.assertLess(shift.max(), 0.015, g['id'])
                self.assertGreater(shift.max(), 0.0, g['id'])
            else:
                self.assertTrue(0.03 < shift.max() <= 0.16, (g['id'], shift.max()))
                self.assertLess(step, 0.02, g['id'])  # slow: small change between consecutive frames

    def test_corner_truth_pixels(self):
        """Unwarp every easy frame (easy frames have no glare, hand or banding) with the truth corners:
        the patch inside each occupied square must differ from bare-board colour more than any empty
        square does. A one-rank corner shift must break this on start frames (negative control)."""
        n, worst, worst_occ, controls = 0, 1e9, 1e9, 0
        for g in self.games:
            if g['difficulty'] != 'easy':
                continue
            for f in g['frames']:
                img = np.asarray(Image.open(self.ROOT_DIR / f['file']).convert('RGB'), float)
                occ = occupancy(f['fen'])
                gap, occ_min = separation(square_means(img, f['corners']), occ)
                self.assertGreater(gap, 5, (f['file'], gap))
                worst, worst_occ, n = min(worst, gap), min(worst_occ, occ_min), n + 1
                if f['index'] == 0:  # negative control: corners shifted one rank toward the a1 side
                    c = np.asarray(f['corners'], float)
                    bad, _ = separation(square_means(img, c + (c[3] - c[0]) / 8), occ)
                    self.assertLess(bad, 0, (f['file'], 'shifted corners still separable'))
                    controls += 1
        print(f'  [{self.ROOT_DIR.name}] pixel corner check: {n} frames, worst gap {worst:.1f} RGB, min occupied '
              f'distance {worst_occ:.1f}; {controls} shifted-corner controls rejected')
        self.assertGreater(n, 200)


class LegacyRoot(SceneRootChecks, unittest.TestCase):
    ROOT_DIR, V2_MODE = V1, False

    def test_determinism_legacy_smoke(self):
        """Default flags regenerate the frozen round-one smoke truth and images byte for byte."""
        if SKIP_DET:
            self.skipTest('--skip-determinism')
        tmp = Path(tempfile.mkdtemp(prefix='screen-game-legacy-'))
        try:
            generate(tmp, ['--smoke-only'])
            new = sha(tmp / 'truth/games.json')
            old = hashlib.sha256(subset_bytes(self.doc, 'smoke')).hexdigest()
            pngs = all(sha(tmp / f['file']) == sha(V1 / f['file']) for g in self.by_split['smoke'] for f in g['frames'])
        finally:
            shutil.rmtree(tmp)
        print(f'  [scenes] frozen games.json sha256 {sha(V1 / "truth/games.json")[:16]}; smoke subset {old[:16]}, '
              f'regenerated {new[:16]}; smoke PNGs identical {pngs}')
        self.assertEqual(old, new)
        self.assertTrue(pngs)


class RepeatedPicturesRoot(SceneRootChecks, unittest.TestCase):
    ROOT_DIR, V2_MODE = V2, True

    def test_three_pictures_per_position(self):
        n_pos = 0
        for g in self.games:
            groups = self.positions(g)
            for p, grp in enumerate(groups):
                n_pos += 1
                self.assertEqual(len(grp), 1 + PER_POSITION, (g['id'], p))
                self.assertEqual({f['positionIndex'] for f in grp}, {p})
                self.assertEqual(len({f['fen'] for f in grp}), 1)
                self.assertEqual([f['kind'] for f in grp][1:], ['repeat'] * PER_POSITION)
                digests = {sha(self.ROOT_DIR / f['file']) for f in grp}
                self.assertEqual(len(digests), len(grp), (g['id'], p, 'pixel-identical pictures'))
                if p == 0:
                    self.assertFalse(any(f['disturbance']['glare'] or f['disturbance']['hand'] for f in grp))
        print(f'  [scenes-v2] {n_pos} positions x {1 + PER_POSITION} distinct pictures')

    def test_sticky_and_moving_disturbances(self):
        """Sticky: same glare spot / hand on every picture of the position, fixed to the board (<= 0.5% of
        board width after mapping through each picture's own corners). Non-sticky: a redrawn glare moves
        >= 5% of board width and a redrawn hand reaches over a different corner."""
        sticky_pos = moved_glare = moved_hand = 0
        for g in self.games:
            for grp in self.positions(g):
                sticky = [f['disturbance']['sticky'] for f in grp]
                self.assertEqual(len(set(sticky)), 1, (g['id'], grp[0]['positionIndex']))
                if sticky[0]:
                    sticky_pos += 1
                    first = grp[0]['scene']
                    self.assertTrue(first['glare'] or first['hand'])
                    for f in grp[1:]:
                        sc = f['scene']
                        self.assertEqual(bool(sc['glare']), bool(first['glare']))
                        self.assertEqual(bool(sc['hand']), bool(first['hand']))
                        if first['glare']:
                            a = to_board(grp[0]['corners'], first['glare']['center'])
                            b = to_board(f['corners'], sc['glare']['center'])
                            self.assertLess(np.abs(a - b).max(), 0.005, f['file'])
                        if first['hand']:
                            self.assertEqual(sc['hand']['displayCorner'], first['hand']['displayCorner'])
                            self.assertEqual(sc['hand']['shapeSeed'], first['hand']['shapeSeed'])
                            a = to_board(grp[0]['corners'], first['hand']['anchor'])
                            b = to_board(f['corners'], sc['hand']['anchor'])
                            self.assertLess(np.abs(a - b).max(), 0.005, f['file'])
                else:
                    glares = [f for f in grp if f['scene']['glare']]
                    for x, y in zip(glares, glares[1:]):
                        d = np.abs(to_board(x['corners'], x['scene']['glare']['center'])
                                   - to_board(y['corners'], y['scene']['glare']['center'])).max()
                        self.assertGreater(d, 0.05, y['file'])
                        moved_glare += 1
                    hands = [f for f in grp if f['scene']['hand']]
                    for x, y in zip(hands, hands[1:]):
                        self.assertNotEqual(x['scene']['hand']['displayCorner'], y['scene']['hand']['displayCorner'])
                        moved_hand += 1
        print(f'  [scenes-v2] sticky disturbed positions {sticky_pos}; non-sticky pairs moved: '
              f'glare {moved_glare}, hand {moved_hand}')
        for split in ('dev', 'heldout'):
            self.assertGreater(sum(f['disturbance']['sticky'] for g in self.by_split[split] for f in g['frames']), 0)
        self.assertGreater(moved_glare, 0)
        self.assertGreater(moved_hand, 0)

    def test_determinism_smoke2(self):
        if SKIP_DET:
            self.skipTest('--skip-determinism')
        args = ['--smoke-only', '--suffix', '2', '--repeats-per-position', str(PER_POSITION)]
        tmp = Path(tempfile.mkdtemp(prefix='screen-game-v2-'))
        try:
            digests = []
            for k in range(2):
                generate(tmp / f'run{k}', args)
                digests.append(sha(tmp / f'run{k}/truth/games.json'))
            pngs = all(sha(tmp / 'run0' / f['file']) == sha(V2 / f['file'])
                       for g in self.by_split['smoke'] for f in g['frames'])
        finally:
            shutil.rmtree(tmp)
        existing = hashlib.sha256(subset_bytes(self.doc, 'smoke2')).hexdigest()
        print(f'  [scenes-v2] smoke2 games.json sha256 run1 {digests[0][:16]} run2 {digests[1][:16]} '
              f'built {existing[:16]}; PNGs identical {pngs}')
        self.assertEqual(digests[0], digests[1])
        self.assertEqual(digests[0], existing)
        self.assertTrue(pngs)


STRESS = BUILD / 'scenes-stress'
FROZEN_SHA = {V1: '584f7a250d89e911e73bed72dad3475ce512855fbb02ab144cf00fc9dd93c4d5',
              V2: 'e09e7952ef86884df3f11b23fe7b8b6dc30868e214fa07e3d0d71c98133a0168'}
VARIANTS = ('style-unfamiliar', 'style-flat', 'theme-colours', 'last-move-highlight', 'coordinates', 'arrows-and-dots',
            'lens-distortion', 'moire', 'motion-blur', 'small-board', 'mid-move', 'baseline')


def patch_means(img, corners, x0, x1, y0, y1):
    """Mean colour of tile-coordinate patch [x0,x1) x [y0,y1) in every square, chess orientation (row 0 = rank 8)."""
    h = board_h(corners)
    px, py = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1))
    means = np.zeros((8, 8, 3))
    for r in range(8):
        for c in range(8):
            pts = np.c_[(c*64 + px).ravel(), (r*64 + py).ravel(), np.ones(px.size)] @ h.T
            x, y = np.rint(pts[:, 0] / pts[:, 2]).astype(int), np.rint(pts[:, 1] / pts[:, 2]).astype(int)
            means[r, c] = img[np.clip(y, 0, img.shape[0]-1), np.clip(x, 0, img.shape[1]-1)].mean(0)
    return means


def unwarp(img, corners, n=512):
    h = board_h(corners)
    px, py = np.meshgrid(np.arange(n) * 512 / n, np.arange(n) * 512 / n)
    pts = np.c_[px.ravel(), py.ravel(), np.ones(px.size)] @ h.T
    x, y = np.rint(pts[:, 0] / pts[:, 2]).astype(int), np.rint(pts[:, 1] / pts[:, 2]).astype(int)
    return img[np.clip(y, 0, img.shape[0]-1), np.clip(x, 0, img.shape[1]-1)].reshape(n, n, 3)


SHADE = (np.add.outer(np.arange(8), np.arange(8)) % 2).astype(bool)  # True = dark square


def deviation(means, ref_mask):
    """RGB distance of every square from the median of ref_mask squares of the same shade."""
    dist = np.zeros((8, 8))
    for s in (False, True):
        ref = np.median(means[ref_mask & (SHADE == s)], 0)
        dist[SHADE == s] = np.linalg.norm(means[SHADE == s] - ref, axis=1)
    return dist


def rc(sq):
    return 8 - int(sq[1]), 'abcdefgh'.index(sq[0])


def read(root, f):
    return np.asarray(Image.open(root / f['file']).convert('RGB'), float)


class StressRoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load(STRESS)
        cls.games = cls.doc['games']
        cls.var = {}
        for g in cls.games:
            cls.var.setdefault(g['stress']['name'], []).append(g)

    def settled(self, g):
        return [f for f in g['frames'] if f['kind'] != 'transition']

    def test_frozen_roots_unchanged(self):
        for root, digest in FROZEN_SHA.items():
            self.assertEqual(sha(root / 'truth/games.json'), digest, root)
        print('  [stress] scenes/ and scenes-v2/ games.json sha256 unchanged')

    def test_schema_and_layout(self):
        d = self.doc
        self.assertEqual((d['schema'], d['frameSize'], d['repeatsPerPosition']), ('screen-game-truth-v1', [1920, 1080], 2))
        self.assertTrue(d['cornerOrder'].startswith('a8,h8,h1,a1'))
        self.assertEqual({g['split'] for g in self.games}, {'stressdev', 'stressheld'})
        self.assertEqual(set(self.var), set(VARIANTS))
        keys = {'index', 'file', 'kind', 'fen', 'moveUci', 'moveSan', 'flags', 'corners', 'disturbance', 'scene',
                'positionIndex', 'transition'}
        for name, gs in self.var.items():
            for split in ('stressdev', 'stressheld'):
                self.assertEqual(sum(g['split'] == split for g in gs), 3, (name, split))
        for g in self.games:
            self.assertEqual(g['difficulty'], 'easy')
            self.assertIn('stress', g)
            groups = {}
            for i, f in enumerate(g['frames']):
                self.assertTrue(keys <= set(f), (g['id'], i))
                self.assertEqual((f['index'], f['file']), (i, f'games/{g["id"]}/{i:03d}.png'))
                self.assertEqual(f['transition'], f['kind'] == 'transition')
                self.assertEqual(set(f['disturbance']), {'glare', 'hand', 'banding', 'sticky'})
                self.assertFalse(any(f['disturbance'].values()))
                if f['kind'] != 'transition':
                    groups.setdefault(f['positionIndex'], []).append(f)
            self.assertTrue(12 <= len(groups) <= 15, (g['id'], len(groups)))
            for p, grp in groups.items():
                self.assertEqual(len(grp), 3, (g['id'], p))
                self.assertEqual(len({f['fen'] for f in grp}), 1)
                self.assertEqual([f['kind'] for f in grp], [('start' if p == 0 else 'move'), 'repeat', 'repeat'])
            for f in g['frames'][:5]:
                with Image.open(STRESS / f['file']) as im:
                    self.assertEqual(im.size, (1920, 1080))
        missing = [f['file'] for g in self.games for f in g['frames'] if not (STRESS / f['file']).is_file()]
        self.assertEqual(missing, [])

    def test_legality_and_transitions(self):
        checks, n_tr = [], 0
        for g in self.games:
            fr = g['frames']
            self.assertEqual(fr[0]['fen'], g['startFen'])
            prev = fr[0]
            for i, f in enumerate(fr[1:], 1):
                if f['kind'] == 'transition':
                    n_tr += 1
                    self.assertEqual(g['stress']['name'], 'mid-move')
                    nxt = fr[i + 1]
                    self.assertEqual((nxt['kind'], nxt['fen'], nxt['moveUci']), ('move', f['fen'], f['transitionMove']))
                    self.assertEqual(f['positionIndex'], nxt['positionIndex'])
                    self.assertEqual(f['positionIndex'] % 3, 0)
                    self.assertIsNone(f['moveUci'])
                    continue
                if f['kind'] == 'repeat':
                    self.assertEqual(f['fen'], prev['fen'])
                else:
                    checks.append({'before': prev['fen'], 'uci': f['moveUci'], 'after': f['fen'], 'san': f['moveSan']})
                prev = f
            if g['stress']['name'] == 'mid-move':
                want = sum(1 for p in {f['positionIndex'] for f in fr} if p > 0 and p % 3 == 0)
                self.assertEqual(sum(f['kind'] == 'transition' for f in fr), want)
        run = subprocess.run(['node', str(LINES), 'verify'], input=json.dumps({'checks': checks}),
                             capture_output=True, text=True, cwd=ROOT, timeout=300)
        res = json.loads(run.stdout)
        print(f'  [stress] chess.js verified {res["checked"]} moves, failures {len(res["failures"])}; '
              f'{n_tr} transition pictures, all in mid-move')
        self.assertTrue(res['ok'], res['failures'][:5])

    def test_no_shared_seed_or_line_with_earlier_splits(self):
        earlier = [g for root in (V1, V2) for g in load(root)['games']]
        line = lambda g: tuple(f['moveUci'] for f in g['frames'] if f['kind'] == 'move')
        self.assertFalse({g['seed'] for g in earlier} & {g['seed'] for g in self.games})
        self.assertFalse({line(g) for g in earlier} & {line(g) for g in self.games})
        for split in ('stressdev', 'stressheld'):  # inside a split only baseline repeats style-unfamiliar's lines
            gs = [g for g in self.games if g['split'] == split and g['stress']['name'] != 'baseline']
            self.assertEqual(len({line(g) for g in gs}), len(gs))
            self.assertEqual(len({g['seed'] for g in gs}), len(gs))
        held = {line(g) for g in self.games if g['split'] == 'stressheld'}
        self.assertFalse(held & {line(g) for g in self.games if g['split'] == 'stressdev'})

    def test_baseline_is_unfamiliar_minus_style(self):
        """Same seed: identical camera, noise and line; pixels differ on occupied squares only."""
        base = {(g['split'], g['id'][-2:]): g for g in self.var['baseline']}
        worst_empty, min_occ = 0.0, 1e9
        for g in self.var['style-unfamiliar']:
            b = base[(g['split'], g['id'][-2:])]
            self.assertEqual((g['seed'], g['startFen']), (b['seed'], b['startFen']))
            self.assertEqual([f['fen'] for f in g['frames']], [f['fen'] for f in b['frames']])
            self.assertEqual([f['corners'] for f in g['frames']], [f['corners'] for f in b['frames']])
            for f, fb in ((g['frames'][0], b['frames'][0]), (g['frames'][-1], b['frames'][-1])):
                diff = np.abs(read(STRESS, f) - read(STRESS, fb))
                d = patch_means(diff, f['corners'], 0, 64, 0, 64).mean(-1)
                occ = occupancy(f['fen'])
                worst_empty, min_occ = max(worst_empty, d[~occ].max()), min(min_occ, d[occ].min())
        print(f'  [stress] baseline vs style-unfamiliar: worst empty-square diff {worst_empty:.2f}, '
              f'smallest occupied-square diff {min_occ:.2f}')
        self.assertLess(worst_empty, 1.5)
        self.assertGreater(min_occ, 2 * max(worst_empty, 0.5))

    def test_style_flat_bases(self):
        """Flat pieces fill ~85% of the square: their base reaches tile x 11-14 near the bottom, where the
        classic artwork has nothing."""
        res = {}
        for name in ('style-flat', 'baseline'):
            hit = tot = 0
            for g in self.var[name]:
                f = g['frames'][0]
                occ = occupancy(f['fen'])
                # display-bottom-left of the tile; for a flipped board that is the chess top-right
                box = (11, 15, 53, 58) if g['whiteAtBottom'] else (49, 53, 6, 11)
                dev = deviation(patch_means(read(STRESS, f), f['corners'], *box), ~occ)
                hit += int((dev[occ] > 20).sum()); tot += int(occ.sum())
            res[name] = hit / tot
        print(f'  [stress] wide-base squares: style-flat {res["style-flat"]:.2f}, baseline {res["baseline"]:.2f}')
        self.assertGreater(res['style-flat'], 0.8)
        self.assertLess(res['baseline'], 0.1)

    def test_theme_colours(self):
        for g in self.var['theme-colours']:
            f = g['frames'][0]
            occ = occupancy(f['fen'])
            m = patch_means(read(STRESS, f), f['corners'], 8, 56, 8, 56)
            light, dark = np.median(m[~occ & ~SHADE], 0), np.median(m[~occ & SHADE], 0)
            lvl = g['stress']['level']
            if lvl == 'brown':
                self.assertGreater(dark[0] - dark[2], 40, g['id'])
            elif lvl == 'blue':
                self.assertGreater(dark[2] - dark[0], 40, g['id'])
            else:
                gap = light.mean() - dark.mean()
                self.assertTrue(10 < gap < 40 and np.ptp(dark) < 12, (g['id'], gap, dark))
        print('  [stress] theme colours: brown, blue and low-contrast gray squares measured in the pictures')

    def test_last_move_highlight(self):
        n = 0
        for g in self.var['last-move-highlight']:
            for f in g['frames']:
                hl = f['scene']['stress'].get('highlight')
                self.assertEqual(hl is None, f['positionIndex'] == 0)
                if hl is None:
                    continue
                mask = np.ones((8, 8), bool)
                for sq in hl:
                    mask[rc(sq)] = False
                dev = deviation(patch_means(read(STRESS, f), f['corners'], 3, 10, 3, 10), mask)
                for sq in hl:
                    self.assertGreater(dev[rc(sq)], 20, (f['file'], sq, dev[rc(sq)]))
                self.assertLess(np.sort(dev[mask])[-1], 20, f['file'])
                n += 1
        print(f'  [stress] highlight: from/to squares tinted in {n} pictures, no other square tinted')

    def test_coordinates(self):
        for g in self.var['coordinates']:
            for f in (g['frames'][0], g['frames'][-1]):
                img = read(STRESS, f)
                left = 0 if g['whiteAtBottom'] else 7  # display left column in chess coordinates
                u = unwarp(img, f['corners'], 512)
                ink, plain = [], []
                for r in range(8):
                    for c in range(8):
                        x0 = c * 64 + (3 if g['whiteAtBottom'] else 51)
                        y0 = r * 64 + (2 if g['whiteAtBottom'] else 49)
                        p = u[y0:y0 + 12, x0:x0 + 10].reshape(-1, 3)
                        (ink if c == left else plain).append(np.percentile(np.linalg.norm(p - np.median(p, 0), axis=1), 90))
                self.assertGreater(min(ink), 40, f['file'])
                self.assertLess(np.median(plain), 15, f['file'])
        print('  [stress] coordinates: rank digits found in every left-column square')

    def test_arrows_and_dots(self):
        pos = with_ov = 0
        for g in self.var['arrows-and-dots']:
            moves = {f['positionIndex']: f['moveUci'] for f in g['frames'] if f['kind'] == 'move'}
            for f in g['frames']:
                if f['kind'] in ('start', 'move'):
                    pos += f['kind'] == 'move'
                ov = f['scene']['stress'].get('overlay')
                if not ov:
                    continue
                with_ov += f['kind'] == 'move'
                p = f['positionIndex']
                related = {u[i:i + 2] for u in (moves.get(p), moves.get(p + 1)) if u for i in (0, 2)}
                self.assertFalse(set(ov['arrow'] or []) & related, f['file'])
                self.assertFalse(set(ov['dots']) & related, f['file'])
                occ = occupancy(f['fen'])
                img = read(STRESS, f)
                dev = deviation(patch_means(img, f['corners'], 26, 38, 26, 38), ~occ)
                for sq in ov['dots']:
                    self.assertFalse(occ[rc(sq)])
                    self.assertGreater(dev[rc(sq)], 12, (f['file'], sq))
                if ov['arrow']:  # arrow body at the midpoint between its two square centres
                    (ra, ca), (rb, cb) = rc(ov['arrow'][0]), rc(ov['arrow'][1])
                    mx, my = (ca + cb) * 32 + 32, (ra + rb) * 32 + 32
                    pts = np.array([[mx + dx, my + dy, 1.0] for dx in range(-3, 4) for dy in range(-3, 4)])
                    q = pts @ board_h(f['corners']).T
                    col = img[np.rint(q[:, 1] / q[:, 2]).astype(int), np.rint(q[:, 0] / q[:, 2]).astype(int)].mean(0)
                    self.assertGreater(col[0] - col[2], 60, (f['file'], col))
        share = with_ov / pos
        print(f'  [stress] arrows/dots on {with_ov}/{pos} positions ({share:.2f}), none touching the last or next move')
        self.assertTrue(0.15 < share < 0.5)

    def test_lens_distortion(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('gen', GEN)
        gen = importlib.util.module_from_spec(spec); spec.loader.exec_module(gen)
        bows = {}
        for g in self.var['lens-distortion']:
            k1s = set()
            for f in g['frames']:
                ln = f['scene']['stress']['lens']
                k1s.add(ln['k1'])
                fwd = gen.lens_forward(np.asarray(ln['undistortedCorners']), ln['k1'])
                self.assertLess(np.abs(fwd - np.asarray(f['corners'])).max(), 0.01, f['file'])
                c, m = np.asarray(f['corners']), np.asarray(ln['edgeMidpoints'])
                bw = c[:, 0].max() - c[:, 0].min()
                cross = lambda a, b: a[0] * b[1] - a[1] * b[0]
                bow = max(abs(cross(c[(i + 1) % 4] - c[i], m[i] - c[i])) / np.linalg.norm(c[(i + 1) % 4] - c[i])
                          for i in range(4)) / bw
                self.assertTrue(0.7 * g['stress']['level'] < bow < 1.3 * g['stress']['level'], (f['file'], bow))
                bows.setdefault(g['stress']['level'], []).append(bow)
            self.assertEqual(len(k1s), 1)
        print('  [stress] lens bow (fraction of board width) per level: ' +
              ', '.join(f'{k}: {np.mean(v):.4f}' for k, v in sorted(bows.items())))

    @staticmethod
    def excess_spread(f):
        """Grey-level spread inside empty squares beyond what the recorded sensor noise explains
        (noise model: luminance sigma + per-channel sigma/2, so grey std = 1.04 sigma). Moire adds to it."""
        u = unwarp(read(STRESS, f), f['corners'], 512).mean(-1)
        occ = occupancy(f['fen'])
        std = np.median([u[r*64 + 12:r*64 + 52, c*64 + 12:c*64 + 52].std()
                         for r in range(8) for c in range(8) if not occ[r, c]])
        return float(np.sqrt(max(0.0, std ** 2 - (13 / 12) * f['scene']['noiseSigma'] ** 2)))

    @staticmethod
    def sharpness(f):
        """Steepest one-sample brightness step across empty-square boundaries, as a share of the light/dark
        contrast; the worse of the two boundary directions (motion blur hits edges across its direction)."""
        u = unwarp(read(STRESS, f), f['corners'], 512).mean(-1)
        occ = occupancy(f['fen'])
        h, v = [], []
        for r in range(8):
            for c in range(8):
                if c > 0 and not occ[r, c] and not occ[r, c - 1]:
                    p = u[r*64 + 16:r*64 + 48, c*64 - 8:c*64 + 8].mean(0)
                    h.append(np.abs(np.diff(p)).max() / abs(p[-3:].mean() - p[:3].mean()))
                if r > 0 and not occ[r, c] and not occ[r - 1, c]:
                    p = u[r*64 - 8:r*64 + 8, c*64 + 16:c*64 + 48].mean(1)
                    v.append(np.abs(np.diff(p)).max() / abs(p[-3:].mean() - p[:3].mean()))
        return float(min(np.median(h), np.median(v)))

    def test_moire_and_motion_blur(self):
        out = []
        for name in ('baseline', 'moire', 'motion-blur'):
            for g in sorted(self.var[name], key=lambda g: (g['split'], str(g['stress']['level']))):
                fr = g['frames'][::7]
                ex = np.median([self.excess_spread(f) for f in fr])
                sh = float(np.median([self.sharpness(f) for f in fr]))  # per-game median: blur angle varies
                lvl = g['stress']['level']
                out.append(f'{g["split"][6:]} {name} {lvl}: excess {ex:.2f}, sharp {sh:.2f}')
                if name == 'baseline':
                    self.assertLess(ex, 0.6, g['id'])
                    self.assertGreater(sh, 0.66, g['id'])
                elif name == 'moire':
                    self.assertGreater(ex, 25 * lvl, (g['id'], ex))
                else:
                    self.assertLess(sh, {3: 0.62, 6: 0.40, 12: 0.22}[lvl], (g['id'], sh))
        print('  [stress] ' + '; '.join(out))

    def test_small_board(self):
        for g in self.var['small-board']:
            fr = [f['scene']['boardWidthFraction'] for f in g['frames']]
            self.assertTrue(abs(min(fr) - g['stress']['level']) < 0.006 and abs(max(fr) - g['stress']['level']) < 0.006,
                            (g['id'], min(fr), max(fr)))
        print('  [stress] small-board width fractions within 0.006 of 0.10 / 0.12 / 0.14')

    def test_corner_truth_on_baseline(self):
        """Pixel corner check (occupied vs empty separable) on every baseline picture; reported for others."""
        report = {}
        for name, gs in sorted(self.var.items()):
            ok = n = 0
            frames = [f for g in gs for f in g['frames']]
            for f in (frames if name == 'baseline' else frames[::6]):
                gap, _ = separation(square_means(read(STRESS, f), f['corners']), occupancy(f['fen']))
                ok += gap > 5; n += 1
            report[name] = f'{ok}/{n}'
            if name == 'baseline':
                self.assertEqual(ok, n)
        print('  [stress] corner check passes (sampled): ' + ', '.join(f'{k} {v}' for k, v in report.items()))

    def test_determinism_one_variant(self):
        if SKIP_DET:
            self.skipTest('--skip-determinism')
        args = ['--stress', 'lens-distortion', '--splits', 'stressdev', '--limit-games', '1']
        tmp = Path(tempfile.mkdtemp(prefix='screen-game-stress-'))
        try:
            digests = []
            for k in range(2):
                generate(tmp / f'run{k}', args)
                digests.append(sha(tmp / f'run{k}/truth/games.json'))
            gid = 'stressdev-lens-distortion-g0'
            g = [g for g in self.games if g['id'] == gid][0]
            pngs = all(sha(tmp / 'run0' / f['file']) == sha(STRESS / f['file']) for f in g['frames'][:6])
        finally:
            shutil.rmtree(tmp)
        d = dict(self.doc); d['games'] = [g]
        existing = hashlib.sha256(json.dumps(d, indent=1).encode()).hexdigest()
        print(f'  [stress] lens-distortion g0 games.json sha256 run1 {digests[0][:16]} run2 {digests[1][:16]} '
              f'built {existing[:16]}; PNGs identical {pngs}')
        self.assertEqual(digests[0], digests[1])
        self.assertEqual(digests[0], existing)
        self.assertTrue(pngs)


class AcrossRoots(unittest.TestCase):
    def test_no_shared_seeds_or_lines(self):
        games = [g for root in (V1, V2) for g in load(root)['games']
                 if base_split(g['split']) in ('dev', 'heldout')]
        splits = {g['split'] for g in games}
        self.assertEqual(splits, {'dev', 'heldout', 'dev2', 'heldout2'})
        seeds = [g['seed'] for g in games]
        self.assertEqual(len(seeds), len(set(seeds)))
        lines = [tuple(f['moveUci'] for f in g['frames'] if f['kind'] == 'move') for g in games]
        self.assertEqual(len(lines), len(set(lines)))
        print(f'  [both] {len(games)} games across dev/heldout/dev2/heldout2: seeds and move lines all distinct')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-determinism', action='store_true')
    a, rest = ap.parse_known_args()
    SKIP_DET = a.skip_determinism
    unittest.main(argv=[sys.argv[0], '-v'] + rest)
