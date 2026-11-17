#!/usr/bin/env python3
"""Piece-type reader v1: basic contract on synthetic rendered boards (not camera evidence).

Run: python3 -B tests/piece_classifier_v1.py
"""
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/recognition'))
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
import piece_classifier_v1 as pc
from render import render

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
# 1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.Qe2 Qe7 (pieces of every type on new squares of both colours)
MIDGAME = 'r1b1k1nr/ppppqppp/2n5/2b1p3/2B1P3/5N2/PPPPQPPP/RNB1K2R w KQkq - 6 5'
QUAD_A = [[70, 66], [700, 60], [698, 702], [60, 712]]
QUAD_B = [[80, 50], [690, 76], [705, 690], [52, 700]]
SMOKE = Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15/scenes')


def board_corners(quad):
    """Image positions of the board's a8, h8, h1, a1 corners for the renderer's 640-px panel mapped onto quad."""
    src = [(0, 0), (640, 0), (640, 640), (0, 640)]
    h = pc._homography(src, quad)
    pts = []
    for u, v in [(64, 64), (576, 64), (576, 576), (64, 576)]:
        p = h @ np.array([u, v, 1.0])
        pts.append([p[0] / p[2] - 0.5, p[1] / p[2] - 0.5])
    return pts


def scene(quad, **extra):
    return {'quad': quad, 'brightness': 1.0, 'blur': 0.3, **extra}


def panel_box(square):
    col, row = 'abcdefgh'.index(square[0]), 8 - int(square[1])
    return [64 + col * 64, 64 + row * 64, 64 + col * 64 + 63, 64 + row * 64 + 63]


def labels(result):
    return {s: r['label'] for s, r in result.items()}


class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cal = pc.calibrate([(render(START, scene(QUAD_A)), board_corners(QUAD_A))], START)

    def check_exact(self, fen, image, corners):
        got = labels(pc.read(image, corners, self.cal))
        truth = pc.placement(fen)
        self.assertEqual(set(got), set(pc.SQUARES))
        for s in pc.SQUARES:
            self.assertEqual(got[s], truth.get(s, 'unsure'), s)   # the reader never claims 'empty'

    def test_start_position_read_on_another_view(self):
        self.check_exact(START, render(START, scene(QUAD_B, brightness=0.85)), board_corners(QUAD_B))

    def test_moved_pieces_named_on_new_square_colours(self):
        self.check_exact(MIDGAME, render(MIDGAME, scene(QUAD_B)), board_corners(QUAD_B))

    def test_board_seen_from_blacks_side(self):
        # The screen shows the board flipped (a8 bottom-right) with pieces upright, as chess sites do for Black.
        def flipped(fen):
            ranks = fen.split()[0].split('/')
            return '/'.join(r[::-1] for r in ranks[::-1]) + ' w - - 0 1'

        def corners(quad):
            tl, tr, br, bl = board_corners(quad)
            return [br, bl, tl, tr]       # a8, h8, h1, a1

        self.assertEqual(pc.screen_rotation(corners(QUAD_B))[0], 2)
        cal = pc.calibrate([(render(flipped(START), scene(QUAD_A)), corners(QUAD_A))], START)
        got = labels(pc.read(render(flipped(MIDGAME), scene(QUAD_B)), corners(QUAD_B), cal))
        truth = pc.placement(MIDGAME)
        for s in pc.SQUARES:
            self.assertEqual(got[s], truth.get(s, 'unsure'), s)

    def test_swapped_same_colour_pieces_are_noticed(self):
        # knight and bishop exchanged: the reader must name what is really there, never the old pieces
        swapped = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RBNQKBNR w KQkq - 0 1'
        got = labels(pc.read(render(swapped, scene(QUAD_B)), board_corners(QUAD_B), self.cal))
        self.assertEqual(got['b1'], 'B')
        self.assertEqual(got['c1'], 'N')

    def test_blank_square_is_unsure(self):
        for square in ('e2', 'e4', 'd8'):  # white piece, empty square, black piece
            img = render(START, scene(QUAD_B, occlusions=[{'box': panel_box(square), 'color': [128, 128, 128]}]))
            rec = pc.read(img, board_corners(QUAD_B), self.cal)[square]
            self.assertEqual(rec['label'], 'unsure', (square, rec))

    def test_heavy_glare_over_piece_is_unsure(self):
        img = np.asarray(render(START, scene(QUAD_B)), float)
        corners = np.asarray(board_corners(QUAD_B))
        h = pc._homography([(0, 0), (8, 0), (8, 8), (0, 8)], corners)
        for square, (u, v) in (('g1', (6.5, 7.5)), ('d8', (3.5, 0.5))):
            p = h @ np.array([u, v, 1.0])
            cx, cy = p[0] / p[2], p[1] / p[2]
            yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
            spot = 230 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 22.0 ** 2))[..., None]
            glared = Image.fromarray(np.clip(img + spot, 0, 255).astype(np.uint8))
            rec = pc.read(glared, corners.tolist(), self.cal)[square]
            self.assertEqual(rec['label'], 'unsure', (square, rec))

    def test_ambiguous_shape_is_unsure(self):
        # g1 shows half knight, half bishop (both white, both on dark squares): no clear winner -> unsure
        tiles, inside = pc._square_tiles(render(START, scene(QUAD_B)), board_corners(QUAD_B))
        g1, c1 = pc.SQUARES.index('g1'), pc.SQUARES.index('c1')
        tiles = tiles.copy()
        tiles[g1] = 0.5 * tiles[g1] + 0.5 * tiles[c1]
        rec = pc.read_tiles(tiles, inside, self.cal)['g1']
        self.assertEqual(rec['label'], 'unsure', rec)
        self.assertEqual(rec['reason'], 'small-margin', rec)

    def test_badly_degraded_square_is_unsure(self):
        # a knight under heavy pixel noise still matches 'N' best, but too poorly to be trusted
        tiles, inside = pc._square_tiles(render(START, scene(QUAD_B)), board_corners(QUAD_B))
        g1 = pc.SQUARES.index('g1')
        tiles = tiles.copy()
        tiles[g1] = tiles[g1] + np.random.default_rng(1).normal(0, 60, tiles[g1].shape)
        rec = pc.read_tiles(tiles, inside, self.cal)['g1']
        self.assertEqual(rec['label'], 'unsure', rec)

    def test_squares_outside_the_image_are_never_named(self):
        img = np.asarray(render(START, scene(QUAD_B)))
        cut = Image.fromarray(img[:, :420].copy())      # right part of the board is cut off
        res = pc.read(cut, board_corners(QUAD_B), self.cal)
        self.assertEqual(set(res), set(pc.SQUARES))
        corners = np.asarray(board_corners(QUAD_B))
        h = pc._homography([(0, 0), (8, 0), (8, 8), (0, 8)], corners)
        outside = 0
        for s in pc.SQUARES:
            col, row = 'abcdefgh'.index(s[0]), 8 - int(s[1])
            xs = [(h @ np.array([col + a, row + b, 1.0])) for a in (0, 1) for b in (0, 1)]
            if max(p[0] / p[2] for p in xs) > 419:
                outside += 1
                self.assertEqual(res[s]['label'], 'unsure', s)
                self.assertEqual(res[s]['reason'], 'outside-image', s)
        self.assertGreater(outside, 8)

    def test_bad_inputs_are_refused(self):
        with self.assertRaises(pc.CalibrationError):
            pc.calibrate([], START)
        img = render(START, scene(QUAD_A))
        mirrored = board_corners(QUAD_A)
        mirrored = [mirrored[1], mirrored[0], mirrored[3], mirrored[2]]
        with self.assertRaises(ValueError):
            pc.read(img, mirrored, self.cal)
        with self.assertRaises(ValueError):
            pc.read(img, [[0, 0], [1, 1], [float('nan'), 2], [3, 3]], self.cal)
        cut = Image.fromarray(np.asarray(img)[:400].copy())
        with self.assertRaises(pc.CalibrationError):
            pc.calibrate([(cut, board_corners(QUAD_A))], START)

    @unittest.skipUnless((SMOKE / 'truth/games.json').exists(), 'scene data not present')
    def test_clean_scene_pictures(self):
        import json
        game = [g for g in json.loads((SMOKE / 'truth/games.json').read_text())['games'] if g['id'] == 'smoke-g01'][0]
        frames = game['frames']
        cal = pc.calibrate([(Image.open(SMOKE / frames[0]['file']), frames[0]['corners'])], game['startFen'])
        for f in (frames[1], frames[-1]):
            got = labels(pc.read(Image.open(SMOKE / f['file']), f['corners'], cal))
            truth = pc.placement(f['fen'])
            for s in pc.SQUARES:
                self.assertEqual(got[s], truth.get(s, 'unsure'), (f['file'], s))


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=1).result
    print(f'{result.testsRun - len(result.failures) - len(result.errors)} of {result.testsRun} tests passed'
          f' ({len(result.skipped)} skipped)')
    sys.exit(0 if result.wasSuccessful() else 1)
