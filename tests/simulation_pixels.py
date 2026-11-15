#!/usr/bin/env python3
"""Development pixel cases, not held-out or physical-board validation."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw, PngImagePlugin, features

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
import recognize as pixel_recognizer
from render import render

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
EXPECTED_ROWS = ('rnbqkbnr', 'pppppppp', '........', '........',
                 '........', '........', 'PPPPPPPP', 'RNBQKBNR')


def png(image, metadata=None):
    output = io.BytesIO()
    image.save(output, format='PNG', pnginfo=metadata)
    return output.getvalue()


def recognize_scene(scene=None, fen=START):
    return pixel_recognizer.recognize_bytes(png(render(fen, scene or {})))


class PixelRecognizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean_image = render(START, {})
        cls.clean_bytes = png(cls.clean_image)
        cls.clean = pixel_recognizer.recognize_bytes(cls.clean_bytes)

    def assert_untrusted(self, result):
        self.assertEqual(result['source'], 'synthetic-pixel-inference')
        self.assertEqual(result['status'], 'needs-human-review')
        self.assertIsNone(result['fen'])
        self.assertIs(result['guidanceAllowed'], False)
        self.assertEqual(result['threshold'], .95)
        self.assertGreaterEqual(result['elapsedMs'], 0)
        self.assertEqual(result['elapsedMs'], result['timing']['totalMs'])
        self.assertEqual(set(result['squares']),
                         {file + rank for rank in '87654321' for file in 'abcdefgh'})
        for cell in result['squares'].values():
            self.assertIn(cell['rawLabel'], '.PNBRQKpnbrqk')
            self.assertIn(cell['confidence'], (0, 1))
            self.assertEqual(cell['label'] != 'unknown', cell['confidence'] >= .95)
            if cell['label'] != 'unknown':
                self.assertEqual(cell['label'], 'empty' if cell['rawLabel'] == '.' else cell['rawLabel'])
        json.dumps(result, allow_nan=False)
        for key in ('sideToMove', 'castling', 'enPassant', 'halfmove', 'fullmove', 'history'):
            self.assertNotIn(key, result)

    def assert_start_pixels(self, result):
        self.assert_untrusted(result)
        self.assertEqual(result['unknownSquares'], 0)
        self.assertEqual(result['rawPlacement'], START.split()[0])
        for row, expected in enumerate(EXPECTED_ROWS):
            for column, label in enumerate(expected):
                cell = result['squares']['abcdefgh'[column] + str(8-row)]
                self.assertEqual(cell['label'], 'empty' if label == '.' else label)

    def test_clean_pixels_cover_entire_board_and_both_piece_colors(self):
        self.assert_start_pixels(self.clean)
        self.assertEqual(self.clean['sourceSha256'], hashlib.sha256(self.clean_bytes).hexdigest())
        self.assertEqual(self.clean['imageSize'], [768, 768])
        self.assertTrue(self.clean['geometry']['available'])
        self.assertTrue(self.clean['rawPlacementAvailable'])

    def test_fixed_development_perspective_and_brightness(self):
        result = recognize_scene({'quad': [[55,72], [704,45], [716,707], [44,694]], 'brightness': .9})
        self.assert_start_pixels(result)

    def test_changed_pixels_produce_changed_proposal_without_game_history(self):
        placement = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR'
        result = recognize_scene(fen=placement + ' b KQkq e3 0 1')
        self.assert_untrusted(result)
        self.assertEqual(result['unknownSquares'], 0)
        self.assertEqual(result['rawPlacement'], placement)
        self.assertEqual(result['squares']['e2']['label'], 'empty')
        self.assertEqual(result['squares']['e4']['label'], 'P')

    def test_hand_and_glare_pixels_abstain_without_empty_fill_in(self):
        hand = recognize_scene({'occlusions': [{'box': [210,210,430,430]}]})
        self.assert_untrusted(hand)
        for file in 'cdef':
            for rank in '6543':
                self.assertEqual(hand['squares'][file+rank]['label'], 'unknown')
        self.assertEqual(hand['squares']['a8']['label'], 'r')
        glare = recognize_scene({'occlusions': [{'box': [65,65,126,126], 'color': [255,255,255]}]})
        self.assert_untrusted(glare)
        self.assertEqual(glare['squares']['a8']['label'], 'unknown')
        self.assertEqual(glare['squares']['h1']['label'], 'R')

    def test_missing_marker_and_unrelated_pixels_abstain_all_squares(self):
        cases = [recognize_scene({'occlusions': [{'box': [16,16,49,49]}]}),
                 pixel_recognizer.recognize_bytes(png(Image.new('RGB', (768,768), (110,110,110))))]
        for result in cases:
            self.assert_untrusted(result)
            self.assertFalse(result['geometry']['available'])
            self.assertFalse(result['rawPlacementAvailable'])
            self.assertEqual(result['unknownSquares'], 64)
            self.assertTrue(all(not cell['rawLabelAvailable'] for cell in result['squares'].values()))

    def test_duplicate_similar_colored_marker_clutter_fails_closed(self):
        image = self.clean_image.copy()
        ImageDraw.Draw(image).ellipse((18,18,42,42), fill=(240,35,35))
        result = pixel_recognizer.recognize_bytes(png(image))
        self.assert_untrusted(result)
        self.assertEqual(result['geometry']['failureReason'], 'ambiguous-marker-components')
        self.assertFalse(result['geometry']['available'])
        self.assertEqual(result['unknownSquares'], 64)

    def test_severe_blur_abstains_and_preserves_unavailable_raw_status(self):
        result = recognize_scene({'blur': 6})
        self.assert_untrusted(result)
        self.assertEqual(result['unknownSquares'], 64)
        self.assertFalse(result['rawPlacementAvailable'])

    def test_unfamiliar_piece_style_abstains_on_occupied_squares(self):
        result = recognize_scene({'style': 'unfamiliar'})
        self.assert_untrusted(result)
        for row, expected in enumerate(EXPECTED_ROWS):
            for column, label in enumerate(expected):
                cell = result['squares']['abcdefgh'[column] + str(8-row)]
                if label != '.':
                    self.assertEqual(cell['label'], 'unknown')
        self.assertEqual(result['unknownSquares'], 32)

    def test_metadata_and_path_do_not_supply_position_or_scene(self):
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('fen', '8/8/8/8/8/8/8/8 b - - 99 999')
        metadata.add_text('scene', '{"style":"unfamiliar","seed":1234}')
        decorated = pixel_recognizer.recognize_bytes(png(self.clean_image, metadata))
        self.assertEqual(decorated['squares'], self.clean['squares'])
        self.assertEqual(decorated['rawPlacement'], self.clean['rawPlacement'])
        self.assertNotEqual(decorated['sourceSha256'], self.clean['sourceSha256'])
        with tempfile.TemporaryDirectory() as directory:
            for name in ('unknown.jpg', 'empty-board-seed-999-black-to-move.png'):
                path = Path(directory) / name
                path.write_bytes(self.clean_bytes)
                result = pixel_recognizer.recognize(path)
                self.assertEqual(result['squares'], self.clean['squares'])
                self.assertEqual(result['sourceSha256'], self.clean['sourceSha256'])

    def test_cli_accepts_only_an_image_and_outputs_review_only_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'frame.png'
            path.write_bytes(self.clean_bytes)
            command = [sys.executable, '-B', str(ROOT / 'scripts/simulation/recognize.py'), str(path)]
            accepted = subprocess.run(command, text=True, capture_output=True, check=True)
            self.assert_start_pixels(json.loads(accepted.stdout))
            rejected = subprocess.run(command + ['--fen', START], text=True, capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(rejected.stdout, '')

    def test_invalid_or_oversized_bytes_do_not_produce_proposals(self):
        for data in (b'', b'not an image', b'x' * (8*1024*1024+1)):
            with self.subTest(length=len(data)), self.assertRaises((ValueError, OSError)):
                pixel_recognizer.recognize_bytes(data)

    def test_hidden_board_rgb_is_rejected_for_full_and_partial_alpha(self):
        transparent = self.clean_image.convert('RGBA')
        transparent.putalpha(0)
        partial = self.clean_image.convert('RGBA')
        partial.putpixel((100,100), (240,35,35,254))
        for image in (transparent, partial):
            with self.subTest(alpha=image.getchannel('A').getextrema()):
                with self.assertRaisesRegex(ValueError, 'Nonopaque'):
                    pixel_recognizer.recognize_bytes(png(image))

    def test_palette_transparency_is_rejected_before_rgb_conversion(self):
        palette = self.clean_image.convert('P', palette=Image.Palette.ADAPTIVE)
        palette.info['transparency'] = palette.getpixel((100,100))
        with self.assertRaisesRegex(ValueError, 'Nonopaque'):
            pixel_recognizer.recognize_bytes(png(palette))

    def test_opaque_rgba_retains_visible_board_recognition(self):
        result = pixel_recognizer.recognize_bytes(png(self.clean_image.convert('RGBA')))
        self.assert_start_pixels(result)
        self.assertEqual(result['squares'], self.clean['squares'])

    @unittest.skipUnless(features.check('webp'), 'Pillow WebP support is unavailable')
    def test_transparent_webp_is_rejected(self):
        image = self.clean_image.convert('RGBA')
        image.putalpha(128)
        output = io.BytesIO()
        image.save(output, format='WEBP', lossless=True)
        with self.assertRaisesRegex(ValueError, 'Nonopaque'):
            pixel_recognizer.recognize_bytes(output.getvalue())


if __name__ == '__main__':
    unittest.main()
