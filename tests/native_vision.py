#!/usr/bin/env python3
"""Native synthetic-boundary tests on Mac CPU; no camera, network or device."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, PngImagePlugin

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'native/ChessCompanionVision'
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
from render import render

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


class NativeVisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='chess-native-vision-tests-')
        cls.directory = Path(cls.temp.name)
        cls.binary = cls.directory / 'native-vision'
        sources = ['ImageDecoder.swift', 'PixelFeatures.swift', 'SyntheticRecognizer.swift', 'NativeVisionCLI.swift']
        subprocess.run(['swiftc', '-O', '-module-cache-path', str(cls.directory / 'module-cache'),
                        *[str(NATIVE / file) for file in sources], '-o', str(cls.binary)], check=True,
                       capture_output=True, timeout=120)
        cls.image = cls.directory / 'image.png'
        render(START, {}).save(cls.image)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_native(self, path, assets=None):
        return subprocess.run([str(self.binary), '--assets', str(assets or NATIVE / 'Assets/classic-templates-v1.json'), str(path)],
                              capture_output=True, text=True, timeout=20)

    def result(self, path):
        process = self.run_native(path)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_classic_pixels_produce_review_only_native_proposal(self):
        result = self.result(self.image)
        self.assertEqual(result['rawPlacement'], START.split()[0])
        self.assertEqual(result['unknownSquares'], 0)
        self.assertEqual(len(result['squares']), 64)
        self.assertEqual(result['sourceSha256'], hashlib.sha256(self.image.read_bytes()).hexdigest())
        self.assertEqual(result['nativeImplementationVersion'], 'swift-synthetic-pixels-v1')
        self.assertEqual(result['pipelineVersion'], 'native-visible-markers-v1')
        self.assertEqual(result['status'], 'needs-human-review')
        self.assertEqual(result['threshold'], .95)
        self.assertIsNone(result['fen'])
        self.assertIs(result['guidanceAllowed'], False)

    def test_filename_and_hidden_fen_text_do_not_supply_piece_labels(self):
        tagged = self.directory / 'kings-only-fake-fen.png'
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('fen', '4k3/8/8/8/8/8/8/4K3 b - - 45 50')
        with Image.open(self.image) as source:
            source.save(tagged, pnginfo=metadata)
        first, second = self.result(self.image), self.result(tagged)
        self.assertNotEqual(first['sourceSha256'], second['sourceSha256'])
        self.assertEqual(first['squares'], second['squares'])
        self.assertEqual(second['rawPlacement'], START.split()[0])

    def test_missing_markers_are_unknown_not_observed_empty(self):
        blank = self.directory / 'blank.png'
        Image.new('RGB', (120, 80), (100, 100, 100)).save(blank)
        result = self.result(blank)
        self.assertEqual(result['unknownSquares'], 64)
        self.assertIs(result['rawPlacementAvailable'], False)
        self.assertIs(result['geometry']['available'], False)
        self.assertTrue(all(cell['label'] == 'unknown' and not cell['rawLabelAvailable'] for cell in result['squares'].values()))

    def test_nonopaque_animated_and_unsupported_media_fail_before_proposal(self):
        alpha = self.directory / 'alpha.png'
        Image.new('RGBA', (32, 32), (100, 100, 100, 254)).save(alpha)
        animated = self.directory / 'animated.png'
        Image.new('RGB', (32, 32), 'red').save(animated, save_all=True, append_images=[Image.new('RGB', (32, 32), 'blue')])
        gif = self.directory / 'image.gif'
        Image.new('RGB', (32, 32)).save(gif)
        for path in (alpha, animated, gif):
            with self.subTest(path=path.name):
                process = self.run_native(path)
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(process.stdout, '')

    def test_exif_orientation_changes_dimensions_once(self):
        path = self.directory / 'oriented.jpg'
        exif = Image.Exif(); exif[274] = 6
        Image.new('RGB', (120, 80), (10, 20, 30)).save(path, exif=exif)
        self.assertEqual(self.result(path)['imageSize'], [80, 120])

    def test_modified_fixed_assets_are_rejected(self):
        original = json.loads((NATIVE / 'Assets/classic-templates-v1.json').read_text())
        for key, value in [('featuresSha256', '0'*64), ('backgrounds', [[0, 0, 0], [255, 255, 255]])]:
            with self.subTest(key=key):
                altered = {**original, key: value}
                path = self.directory / 'foreign-assets.json'
                path.write_text(json.dumps(altered))
                result = self.run_native(self.image, assets=path)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
