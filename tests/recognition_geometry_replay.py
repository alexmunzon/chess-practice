#!/usr/bin/env python3
"""Artifact-boundary regressions. No detector, classifier inference or hardware."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/recognition'))
from replay_geometry_comparison import (MODEL_HASHES, MANUAL_MODE, SQUARES,
                                       automatic_squares, contained,
                                       orientation_permutation, read_json, validate_prediction, verify_geometry_record)


def record():
    return {'sourceSha256': 'a' * 64, 'imageSize': [100, 100],
            'orientation': 'printed-board-coordinates',
            'screenCornersTLTRBRBL': [[10, 10], [90, 10], [90, 90], [10, 90]],
            'canonicalCornersA8H8H1A1': [[90, 10], [90, 90], [10, 90], [10, 10]]}


def prediction():
    return {'source': 'real-image-inference', 'status': 'needs-human-review',
            'guidanceAllowed': False, 'fen': None, 'sourceSha256': 'a' * 64,
            'imageSize': [100, 100], 'modelHashes': dict(MODEL_HASHES),
            'threshold': .95, 'calibrationMode': MANUAL_MODE, 'orientation': 'white-bottom',
            'squares': {square: {'rawLabel': '.', 'label': 'empty', 'confidence': .99}
                        for square in SQUARES}}


def geometry():
    return {'source': 'prerecorded-image', 'humanConfirmed': False, 'fen': None,
            'mode': 'automatic-rectangle-or-grid-and-checker-heuristic',
            'sourceSha256': 'a' * 64, 'imageSize': [100, 100], 'status': 'abstained',
            'squares': [], 'selectedGeometryMethod': None}


class GeometryReplayTests(unittest.TestCase):
    def test_annotation_fixes_canonical_orientation_without_predictions(self):
        self.assertEqual(orientation_permutation(record()), [1, 2, 3, 0])
        for change in [
                {'orientation': 'unknown'},
                {'canonicalCornersA8H8H1A1': list(reversed(record()['canonicalCornersA8H8H1A1']))},
                {'canonicalCornersA8H8H1A1': [[-1, 10], [90, 90], [10, 90], [10, 10]]},
                {'screenCornersTLTRBRBL': [[float('nan'), 10], [90, 10], [90, 90], [10, 90]]}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                orientation_permutation(record() | change)

    def test_same_classifier_policy_rejects_mixed_model_state_source_threshold_and_orientation(self):
        original = prediction()
        self.assertEqual(validate_prediction(original, record(), MANUAL_MODE, .95), original['squares'])
        for change in [{'sourceSha256': 'b' * 64}, {'imageSize': [99, 100]},
                       {'modelHashes': {}}, {'threshold': .9}, {'guidanceAllowed': True},
                       {'fen': 'invented'}, {'status': 'ready'}, {'source': 'synthetic'},
                       {'orientation': 'black-bottom'}, {'calibrationMode': 'other-model'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_prediction(original | change, record(), MANUAL_MODE, .95)

    def test_acceptance_must_match_frozen_threshold_and_finite_scores(self):
        for cell in [{'confidence': .94}, {'confidence': float('nan')},
                     {'confidence': True}, {'rawLabel': 'P'}, {'label': 'unknown'},
                     {'rawLabel': 'unknown'}]:
            proposal = prediction()
            proposal['squares']['a8'].update(cell)
            with self.subTest(cell=cell), self.assertRaises(ValueError):
                validate_prediction(proposal, record(), MANUAL_MODE, .95)
        proposal = prediction()
        proposal['squares']['a8'].update(confidence=.94, label='unknown')
        self.assertEqual(validate_prediction(proposal, record(), MANUAL_MODE, .95)['a8']['label'], 'unknown')

    def test_runtime_error_is_not_geometry_abstention(self):
        self.assertIsNone(automatic_squares(geometry(), None, record(), .95))
        for change in [{'status': 'execution-error'}, {'sourceSha256': 'b' * 64},
                       {'mode': 'manual-four-corner'}, {'humanConfirmed': True},
                       {'corners': record()['screenCornersTLTRBRBL']},
                       {'selectedGeometryMethod': 'numpy-grid-line-extrapolation'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                automatic_squares(geometry() | change, None, record(), .95)
        with self.assertRaises(ValueError):
            automatic_squares(geometry(), prediction(), record(), .95)

    def test_detected_geometry_needs_classification_and_exact_geometry_orientation_linkage(self):
        detected = geometry() | {'status': 'needs-human-confirmation',
                                  'corners': record()['screenCornersTLTRBRBL'],
                                  'squares': [{} for _ in SQUARES]}
        with self.assertRaisesRegex(ValueError, 'classification not run'):
            automatic_squares(detected, None, record(), .95)
        linked = record() | {'geometryArtifactSha256': 'c' * 64}
        pred = prediction() | {'calibrationMode': 'automatic-canonical-fixed-orientation',
                                'geometryArtifactSha256': 'c' * 64, 'canonicalPermutation': [1, 2, 3, 0]}
        self.assertEqual(automatic_squares(detected, pred, linked, .95), pred['squares'])
        for change in [{'geometryArtifactSha256': 'd' * 64}, {'canonicalPermutation': [0, 1, 2, 3]},
                       {'geometryArtifactSha256': None}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                automatic_squares(detected, pred | change, linked, .95)

    def test_detected_geometry_requires_exactly_four_valid_corners(self):
        for corners in [[[10, 10]], [[10, 10]] * 5,
                        [[10, 10], [90, 90], [90, 10], [10, 90]],
                        [[float('nan'), 10], [90, 10], [90, 90], [10, 90]],
                        [[-1, 10], [90, 10], [90, 90], [10, 90]],
                        ['bad', [90, 10], [90, 90], [10, 90]]]:
            detected = geometry() | {'status': 'needs-human-confirmation', 'corners': corners,
                                      'squares': [{} for _ in SQUARES]}
            with self.subTest(corners=corners), self.assertRaises(ValueError):
                automatic_squares(detected, prediction(), record(), .95)

    def test_calibration_file_cannot_borrow_an_unrelated_runs_provenance(self):
        item = record() | {'id': 'frame-0', 'timestampSeconds': 0}
        saved = {'id': 'frame-0', 'sourceSha256': 'a' * 64, 'imageSize': [100, 100],
                 'timestampSeconds': 0, 'status': 'abstained', 'detected': False,
                 'geometryMethod': None, 'prediction': None}
        verify_geometry_record(geometry(), saved, item)
        for change in [{'id': 'frame-1'}, {'timestampSeconds': 4}, {'detected': True},
                       {'status': 'execution-error'}, {'sourceSha256': 'b' * 64},
                       {'prediction': item['screenCornersTLTRBRBL']}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_geometry_record(geometry(), saved | change, item)

    def test_duplicate_keys_and_nonfinite_json_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix='chess-replay-json-') as directory:
            path = Path(directory) / 'input.json'
            for content in ['{"status":"abstained","status":"execution-error"}', '{"score":NaN}']:
                path.write_text(content)
                with self.assertRaises(ValueError):
                    read_json(path)
            path.write_text('{"score":0.95}')
            self.assertEqual(read_json(path), {'score': .95})

    def test_artifact_paths_cannot_escape_source_root(self):
        with tempfile.TemporaryDirectory(prefix='chess-replay-path-') as directory:
            root = Path(directory)
            self.assertEqual(contained(root, 'video/frame.png'), (root / 'video/frame.png').resolve())
            for relative in ['../other/video.png', str(root / 'absolute.png')]:
                with self.assertRaises(ValueError):
                    contained(root, relative)


if __name__ == '__main__':
    unittest.main()
