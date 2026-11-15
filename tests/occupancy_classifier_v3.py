#!/usr/bin/env python3
"""Square reader v3: synthetic rendered boards only, not camera evidence.

Part 1 repeats every case of tests/occupancy_classifier.py against v3 (no regression on the original
marker corpus style). Part 2 adds v3 cases: refresh banding and bright spots over bare squares must
never produce a confident piece, and the start-picture negative controls must stay rejected.

Run: python3 -B tests/occupancy_classifier_v3.py
"""
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/recognition'))
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
import occupancy_classifier_v3 as oc
from appearance import BOARD_ORIGIN, TILE_SIZE
from render import render

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
AFTER_E4 = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1'
SCENE = {'quad': [[70, 66], [700, 60], [698, 702], [60, 712]], 'brightness': 1.0, 'blur': 0.1}


def tile_box(square):
    col, row = 'abcdefgh'.index(square[0]), 8 - int(square[1])
    x, y = BOARD_ORIGIN[0] + col * TILE_SIZE, BOARD_ORIGIN[1] + row * TILE_SIZE
    return x, y, x + TILE_SIZE, y + TILE_SIZE


def centre(square):
    x0, y0, x1, y1 = tile_box(square)
    return (x0 + x1) / 2, (y0 + y1) / 2


def banded(panel, amp, period, phase=0.3):
    a = np.asarray(panel, float)
    yy = np.arange(a.shape[0])[:, None, None]
    return Image.fromarray(np.clip(a * (1 + amp * np.sin(2 * np.pi * yy / period + phase)), 0, 255).astype(np.uint8))


def spot(panel, cx, cy, amp, sigma):
    a = np.asarray(panel, float)
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    g = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))[..., None]
    return Image.fromarray(np.clip(a + amp * g, 0, 255).astype(np.uint8))


class OriginalCases(unittest.TestCase):
    """Every case from tests/occupancy_classifier.py, pointed at v3."""

    @classmethod
    def setUpClass(cls):
        cls.start_panel = oc.rectify(render(START, SCENE))
        cls.cal = oc.calibrate(cls.start_panel, oc.occupancy_from_fen(START))

    def test_calibration_learns_references(self):
        self.assertEqual(len(self.cal['emptyRef']), 2)
        self.assertEqual(set(self.cal['fillRef']), {'white', 'black'})
        self.assertGreater(np.mean(self.cal['fillRef']['white']), np.mean(self.cal['fillRef']['black']))

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
            self.assertEqual(cell['label'], truth[square], (square, cell))
            self.assertGreaterEqual(cell['confidence'], oc.ABSTAIN_BELOW)

    def test_occluded_square_returns_unknown(self):
        panel = self.start_panel.copy()
        draw = ImageDraw.Draw(panel)
        draw.rectangle(tile_box('d2'), fill=(149, 111, 88))
        x0, y0, x1, y1 = tile_box('d4')
        draw.ellipse((x0 + 20, y0 + 16, x1 - 20, y1 - 16), fill=(196, 150, 120))
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
        ImageDraw.Draw(image).rectangle((0, 0, 767, 140), fill=(62, 66, 70))
        result, geometry_ok = oc.classify_image(image, self.cal)
        self.assertFalse(geometry_ok)
        self.assertTrue(all(cell['label'] == 'unknown' for cell in result.values()))

    def test_heavily_blurred_frame_abstains_instead_of_guessing(self):
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
        for key in ('FG_DISTANCE', 'EMPTY_MAX_FG', 'PIECE_MIN_FG', 'COLOR_VOTE_MIN', 'ABSTAIN_BELOW',
                    'EDGE_LEVEL', 'LOCAL_MAX_SHIFT', 'LOCAL_MAX_STEP'):
            self.assertIn(key, policy)
        self.assertEqual(self.cal['policy'], policy)


class V3Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start_panel = oc.rectify(render(START, SCENE))
        cls.cal = oc.calibrate(cls.start_panel, oc.occupancy_from_fen(START))
        cls.later = oc.rectify(render(AFTER_E4, SCENE))
        cls.truth = oc.occupancy_from_fen(AFTER_E4)

    def assert_no_wrong(self, result, what):
        wrong = [(s, c['label'], self.truth[s]) for s, c in result.items()
                 if c['label'] not in ('unknown', self.truth[s])]
        self.assertEqual(wrong, [], what)

    def test_banding_never_gives_a_confident_wrong_square(self):
        for amp in (0.05, 0.1, 0.2, 0.3):
            for period in (16, 40, 100):
                self.assert_no_wrong(oc.classify(banded(self.later, amp, period), self.cal), f'banding {amp} {period}')

    def test_mild_banding_is_corrected_not_just_withheld(self):
        result = oc.classify(banded(self.later, 0.05, 100), self.cal)
        known = sum(c['label'] != 'unknown' for c in result.values())
        self.assertGreaterEqual(known, 56, known)

    def test_bright_spot_over_bare_square_is_never_a_piece(self):
        for square in ('d5', 'e5', 'c3', 'f6'):
            for amp in (40, 90, 150, 220):
                for sigma in (8, 16, 28):
                    result = oc.classify(spot(self.later, *centre(square), amp, sigma), self.cal)
                    self.assertIn(result[square]['label'], ('empty', 'unknown'), (square, amp, sigma, result[square]))
                    self.assert_no_wrong(result, f'spot {square} {amp} {sigma}')

    def test_start_rejects_position_one_square_off(self):
        claim = oc.occupancy_from_fen(START)
        for square, other in (('e2', 'empty'), ('e4', 'white'), ('d8', 'white'), ('a5', 'black')):
            c = dict(claim); c[square] = other
            with self.assertRaises(oc.CalibrationError, msg=square):
                oc.calibrate(self.start_panel, c)

    def test_start_rejects_rotated_and_flipped_board(self):
        claim = oc.occupancy_from_fen(START)
        for panel in (self.start_panel.rotate(90), self.start_panel.rotate(180),
                      self.start_panel.transpose(Image.FLIP_TOP_BOTTOM)):
            with self.assertRaises(oc.CalibrationError):
                oc.calibrate(panel, claim)

    def test_start_rejects_hand_or_glare_over_pieces(self):
        claim = oc.occupancy_from_fen(START)
        hand = self.start_panel.copy()
        x0, y0, _, _ = tile_box('c2')
        ImageDraw.Draw(hand).ellipse((x0 - 10, y0 + 10, x0 + 120, y0 + 140), fill=(196, 150, 120))
        with self.assertRaises(oc.CalibrationError):
            oc.calibrate(hand, claim)
        glare = spot(self.start_panel, *centre('d7'), 200, 30)
        with self.assertRaises(oc.CalibrationError):
            oc.calibrate(glare, claim)

    def test_banded_start_is_accepted_when_local_correction_explains_it(self):
        cal = oc.calibrate(banded(self.start_panel, 0.05, 100), oc.occupancy_from_fen(START))
        self.assert_no_wrong(oc.classify(self.later, cal), 'clean frame after banded start')


if __name__ == '__main__':
    unittest.main(verbosity=2)
