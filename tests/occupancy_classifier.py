#!/usr/bin/env python3
"""Three-way occupancy prototype: synthetic rendered boards only, not camera evidence.

Run: python3 -B tests/occupancy_classifier.py
"""
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/recognition'))
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
import occupancy_classifier as oc
from appearance import BOARD_ORIGIN, TILE_SIZE
from render import render

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
AFTER_E4 = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1'
SCENE = {'quad': [[70, 66], [700, 60], [698, 702], [60, 712]], 'brightness': 1.0, 'blur': 0.1}


def tile_box(square):
    col, row = 'abcdefgh'.index(square[0]), 8 - int(square[1])
    x, y = BOARD_ORIGIN[0] + col * TILE_SIZE, BOARD_ORIGIN[1] + row * TILE_SIZE
    return x, y, x + TILE_SIZE, y + TILE_SIZE


class OccupancyClassifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start_panel = oc.rectify(render(START, SCENE))
        cls.cal = oc.calibrate(cls.start_panel, oc.occupancy_from_fen(START))

    def test_calibration_learns_six_references(self):
        self.assertEqual(len(self.cal['emptyRef']), 2)
        self.assertEqual(set(self.cal['pieceRef']), {'white-light', 'white-dark', 'black-light', 'black-dark'})
        for parity in ('light', 'dark'):
            self.assertGreater(np.mean(self.cal['pieceRef'][f'white-{parity}']),
                               np.mean(self.cal['pieceRef'][f'black-{parity}']))

    def test_calibration_rejects_frame_that_does_not_match_start(self):
        wrong_position = oc.rectify(render(AFTER_E4, SCENE))
        with self.assertRaises(oc.CalibrationError) as ctx:
            oc.calibrate(wrong_position, oc.occupancy_from_fen(START))
        self.assertIn('e2', str(ctx.exception))
        self.assertIn('e4', str(ctx.exception))

    def test_calibration_rejects_swapped_colour_claim(self):
        claim = oc.occupancy_from_fen(START)
        claim['a1'], claim['a8'] = 'black', 'white'
        with self.assertRaises(oc.CalibrationError):
            oc.calibrate(self.start_panel, claim)

    def test_calibration_rejects_incomplete_occupancy(self):
        claim = oc.occupancy_from_fen(START)
        del claim['h8']
        with self.assertRaises(oc.CalibrationError):
            oc.calibrate(self.start_panel, claim)

    def test_later_position_is_classified_three_way(self):
        result = oc.classify(oc.rectify(render(AFTER_E4, SCENE)), self.cal)
        truth = oc.occupancy_from_fen(AFTER_E4)
        self.assertEqual(set(result), set(oc.SQUARES))
        for square, cell in result.items():
            self.assertIn(cell['label'], oc.LABELS)
            self.assertTrue(0 <= cell['confidence'] <= 1)
            self.assertEqual(cell['label'], truth[square], square)
            self.assertGreaterEqual(cell['confidence'], oc.ABSTAIN_BELOW)

    def test_occluded_square_returns_unknown(self):
        panel = self.start_panel.copy()
        draw = ImageDraw.Draw(panel)
        draw.rectangle(tile_box('d2'), fill=(149, 111, 88))          # covers a whole square
        x0, y0, x1, y1 = tile_box('d4')
        draw.ellipse((x0 + 20, y0 + 16, x1 - 20, y1 - 16), fill=(196, 150, 120))  # fingertip inside an empty square
        result = oc.classify(panel, self.cal)
        for square in ('d2', 'd4'):
            self.assertEqual(result[square]['label'], 'unknown', (square, result[square]))
            self.assertLess(result[square]['confidence'], oc.ABSTAIN_BELOW)
            self.assertTrue(result[square]['reasons'])
        self.assertEqual(result['e2']['label'], 'white')
        self.assertEqual(result['d5']['label'], 'empty')

    def test_specular_glare_square_returns_unknown(self):
        panel = np.array(self.start_panel)
        x0, y0, x1, y1 = tile_box('c6')
        panel[y0 + 12:y1 - 12, x0 + 12:x1 - 12] = 255
        result = oc.classify(Image.fromarray(panel, 'RGB'), self.cal)
        self.assertEqual(result['c6']['label'], 'unknown')

    def test_missing_geometry_abstains_everywhere(self):
        image = render(START, SCENE)
        ImageDraw.Draw(image).rectangle((0, 0, 767, 140), fill=(62, 66, 70))  # hide the top markers
        result, geometry_ok = oc.classify_image(image, self.cal)
        self.assertFalse(geometry_ok)
        self.assertTrue(all(cell['label'] == 'unknown' for cell in result.values()))

    def test_heavily_blurred_frame_abstains_instead_of_guessing(self):
        from PIL import ImageFilter
        blurred = self.start_panel.filter(ImageFilter.GaussianBlur(5))
        result = oc.classify(blurred, self.cal)
        self.assertTrue(all(cell['label'] == 'unknown' for cell in result.values()))
        self.assertIn('frame-too-blurry', result['a1']['reasons'])

    def test_deterministic(self):
        panel = oc.rectify(render(AFTER_E4, SCENE))
        first = oc.classify(panel, self.cal)
        second = oc.classify(panel.copy(), oc.calibrate(self.start_panel.copy(), oc.occupancy_from_fen(START)))
        self.assertEqual(first, second)

    def test_policy_is_recorded(self):
        policy = oc.policy()
        for key in ('FG_DISTANCE', 'EMPTY_MAX_FG', 'PIECE_MIN_FG', 'COLOR_VOTE_MIN', 'ABSTAIN_BELOW'):
            self.assertIn(key, policy)
        self.assertEqual(self.cal['policy'], policy)


if __name__ == '__main__':
    unittest.main(verbosity=2)
