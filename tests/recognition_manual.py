#!/usr/bin/env python3
"""Manual geometry/indexing regression; synthetic pixels, no model or Vision."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/recognition'))
import manual_photo as manual
from photo_pieces import placement


class StubClassifier:
    def __init__(self):
        self.calls = []

    def recognize(self, image, geometry, threshold):
        self.calls.append((Path(image), copy.deepcopy(geometry), threshold))
        cells = {}
        for index, square in enumerate(manual.SQUARES):
            raw = ('.' + manual.CLASSES)[index % 13]
            confidence = .96 + index / 10000 if index % 3 else .7 + index / 10000
            label = ('empty' if raw == '.' else raw) if confidence >= threshold else 'unknown'
            cells[square] = {'rawLabel': raw, 'label': label, 'confidence': confidence,
                             'occupancyScore': .8, 'classScores': {}}
        return {'schemaVersion': 1, 'source': 'real-image-inference',
                'sourceSha256': geometry['sourceSha256'], 'imageSize': geometry['imageSize'],
                'modelHashes': manual.MODEL_HASHES, 'threshold': threshold,
                'elapsedMs': 1, 'squares': cells,
                'rawPlacement': placement([cells[key]['rawLabel'] for key in manual.SQUARES]),
                'status': 'needs-human-review', 'fen': None, 'guidanceAllowed': False,
                'orientation': 'white-bottom', 'limitations': []}


class ManualPhotoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='chess-manual-test-')
        self.folder = Path(self.temp.name)
        self.image = self.folder / 'board.png'
        Image.new('RGB', (100, 100), (20, 70, 160)).save(self.image)
        self.request = {'sourceSha256': hashlib.sha256(self.image.read_bytes()).hexdigest(),
                        'imageSize': [100, 100], 'corners': [[10, 10], [90, 10], [90, 90], [10, 90]],
                        'topLeftSquare': 'a8', 'geometryReviewed': False}

    def tearDown(self):
        self.temp.cleanup()

    def reviewed(self, top_left='a8'):
        request = copy.deepcopy(self.request)
        request['topLeftSquare'] = top_left
        request['geometryReviewed'] = True
        request['calibrationId'] = manual.calibration_id(request)
        return request

    def test_preview_has_64_canonical_polygons_without_confirmation_or_paths(self):
        result = manual.preview(self.image, self.request)
        self.assertEqual(len(result['squares']), 64)
        self.assertEqual({cell['square'] for cell in result['squares']}, set(manual.SQUARES))
        self.assertEqual(result['squares'][0], {'square': 'a8', 'sourcePolygon': [[10., 10.], [20., 10.], [20., 20.], [10., 20.]]})
        self.assertEqual(result['status'], 'needs-geometry-review')
        self.assertIsNone(result['fen'])
        self.assertIs(result['guidanceAllowed'], False)
        self.assertNotIn(str(self.folder), json.dumps(result))
        self.assertNotIn('humanConfirmed', result)

    def test_all_orientations_reindex_every_cell_without_rotating_crop_frame(self):
        expected = {'a8': lambda r, c: (r, c), 'h8': lambda r, c: (c, 7-r),
                    'h1': lambda r, c: (7-r, 7-c), 'a1': lambda r, c: (7-c, r)}
        for top_left, mapping in expected.items():
            with self.subTest(top_left=top_left):
                request = self.reviewed(top_left)
                classifier = StubClassifier()
                result = manual.recognition(self.image, request, classifier=classifier)
                image, geometry, threshold = classifier.calls[0]
                self.assertEqual(image, self.image)
                self.assertEqual(geometry['corners'], self.request['corners'])
                self.assertEqual(geometry['orientation'], 'white-bottom')
                self.assertEqual(threshold, .95)
                for index in range(64):
                    row, column = mapping(index // 8, index % 8)
                    square = 'abcdefgh'[column] + str(8-row)
                    self.assertEqual(result['squares'][square]['rawLabel'], ('.' + manual.CLASSES)[index % 13])
                    self.assertAlmostEqual(result['squares'][square]['confidence'], (.96 if index % 3 else .7) + index / 10000)
                self.assertEqual(result['rawPlacement'], placement([result['squares'][key]['rawLabel'] for key in manual.SQUARES]))
                self.assertEqual(result['pipelineVersion'], 'image-order-crops-v1')
                self.assertEqual(result['topLeftSquare'], top_left)
                self.assertIs(result['geometryHumanReviewed'], True)
                self.assertIsNone(result['completeAcceptedPlacement'])
                self.assertIsNone(result['fen'])
                self.assertIs(result['guidanceAllowed'], False)
                self.assertEqual(result['status'], 'needs-human-review')

    def test_preview_orientation_changes_names_not_source_polygons(self):
        baseline = manual.preview(self.image, self.request)
        for top_left in manual.TOP_LEFT_SQUARES:
            request = {**self.request, 'topLeftSquare': top_left}
            result = manual.preview(self.image, request)
            self.assertEqual(result['squares'][0]['square'], top_left)
            self.assertEqual([cell['sourcePolygon'] for cell in result['squares']], [cell['sourcePolygon'] for cell in baseline['squares']])

    def test_changed_geometry_orientation_or_source_invalidates_review_before_inference(self):
        for field, value in [('corners', [[11, 10], [90, 10], [90, 90], [10, 90]]),
                             ('topLeftSquare', 'a1'), ('sourceSha256', '0' * 64),
                             ('imageSize', [101, 100]), ('geometryReviewed', False),
                             ('calibrationId', '0' * 64)]:
            with self.subTest(field=field):
                request = self.reviewed()
                request[field] = value
                classifier = StubClassifier()
                with self.assertRaises(ValueError):
                    manual.recognition(self.image, request, classifier=classifier)
                self.assertEqual(classifier.calls, [])

    def test_preview_and_recognition_have_distinct_review_contracts(self):
        with self.assertRaises(ValueError):
            manual.preview(self.image, self.reviewed())
        with self.assertRaises(ValueError):
            manual.preview(self.image, {**self.request, 'calibrationId': 'a' * 64})
        request = self.reviewed()
        del request['calibrationId']
        with self.assertRaises(ValueError):
            manual.recognition(self.image, request, classifier=StubClassifier())

    def test_schema_and_corner_order_fail_closed(self):
        wrong = [dict(self.request, unknown=True), dict(self.request, geometryReviewed=0),
                 dict(self.request, imageSize=[True, 100]), dict(self.request, imageSize=[8193, 100]),
                 dict(self.request, imageSize=[6000, 6000]), dict(self.request, topLeftSquare='guess')]
        points = self.request['corners']
        for corners in [points[1:] + points[:1], points[2:] + points[:2], points[::-1],
                        [[10, 10]] * 4, [[-1, 10], *points[1:]], [[True, 10], *points[1:]],
                        [[float('nan'), 10], *points[1:]], [[float('inf'), 10], *points[1:]]]:
            wrong.append(dict(self.request, corners=corners))
        for request in wrong:
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    manual.validate_request(request)

    def test_calibration_digest_normalizes_negative_zero_and_integer_floats(self):
        request = {**self.request, 'corners': [[0, 0], [90, 0], [90, 90], [0, 90]]}
        same = {**request, 'corners': [[-0., 0.], [90., -0.], [90., 90.], [0., 90.]]}
        self.assertEqual(manual.calibration_id(request), manual.calibration_id(same))
        self.assertNotEqual(manual.calibration_id(request), manual.calibration_id({**request, 'topLeftSquare': 'h1'}))

    def test_actual_image_identity_and_format_checked(self):
        Image.new('RGB', (100, 100), (90, 40, 20)).save(self.image)
        with self.assertRaises(ValueError):
            manual.preview(self.image, self.request)
        gif = self.folder / 'board.gif'
        Image.new('RGB', (100, 100)).save(gif)
        with self.assertRaises(ValueError):
            manual.image_identity(gif)

    def test_exif_oriented_dimensions_are_required_and_animation_rejected(self):
        image = self.folder / 'oriented.jpg'
        exif = Image.Exif()
        exif[274] = 6
        Image.new('RGB', (120, 80)).save(image, exif=exif)
        digest, size = manual.image_identity(image)
        self.assertEqual(size, [80, 120])
        request = {**self.request, 'sourceSha256': digest, 'imageSize': size,
                   'corners': [[0, 0], [80, 0], [80, 120], [0, 120]]}
        self.assertEqual(manual.preview(image, request)['imageSize'], [80, 120])
        raw_size_request = {**request, 'imageSize': [120, 80],
                            'corners': [[0, 0], [120, 0], [120, 80], [0, 80]]}
        with self.assertRaises(ValueError):
            manual.preview(image, raw_size_request)
        animated = self.folder / 'animated.png'
        Image.new('RGB', (10, 10), 'red').save(animated, save_all=True,
                                             append_images=[Image.new('RGB', (10, 10), 'blue')])
        with self.assertRaises(ValueError):
            manual.image_identity(animated)

    def test_classifier_cannot_override_identity_threshold_or_guidance_gate(self):
        for key, value in [('sourceSha256', '0'*64), ('threshold', .5), ('guidanceAllowed', True),
                           ('fen', 'invented'), ('elapsedMs', float('nan'))]:
            class BadClassifier(StubClassifier):
                def recognize(self, *args):
                    result = super().recognize(*args)
                    result[key] = value
                    return result
            with self.subTest(key=key), self.assertRaises(ValueError):
                manual.recognition(self.image, self.reviewed(), classifier=BadClassifier())

    def test_cli_preview_uses_same_review_only_schema(self):
        request = self.folder / 'request.json'
        request.write_text(json.dumps(self.request))
        process = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/recognition/manual_photo.py'),
                                  'preview', str(self.image), str(request)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result['calibrationId'], manual.calibration_id(self.request))
        self.assertEqual(result['status'], 'needs-geometry-review')
        self.assertIs(result['guidanceAllowed'], False)


if __name__ == '__main__':
    unittest.main()
