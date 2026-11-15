#!/usr/bin/env python3
"""Audit recorded geometry/control evidence. Never runs inference or claims a new holdout."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from paired_metrics import summarize
from photo_pieces import MODEL_HASHES

ROOT = Path(__file__).resolve().parents[2]
SQUARES = tuple(f + r for r in '87654321' for f in 'abcdefgh')
MANUAL_MODE = 'manual-canonical-corners-cstr'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON value: ' + value)
    require(Path(path).stat().st_size <= 4 * 1024 * 1024, 'JSON artifact too large')
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=invalid)


def contained(root, relative):
    require(isinstance(relative, str) and not Path(relative).is_absolute(), 'Relative artifact path required')
    result = (root / relative).resolve()
    require(result.is_relative_to(root.resolve()), 'Artifact path escapes evidence root')
    return result


def validate_corners(corners, size):
    require(len(size) == 2 and all(type(x) is int and x > 0 for x in size), 'Invalid image size')
    require(isinstance(corners, list) and len(corners) == 4, 'Four corners required')
    require(all(isinstance(p, list) and len(p) == 2 and all(type(x) in (int, float) and math.isfinite(x) for x in p)
                and 0 <= p[0] <= size[0] and 0 <= p[1] <= size[1] for p in corners), 'Invalid corner coordinates')
    cross = []
    for i in range(4):
        a, b, c = corners[i], corners[(i + 1) % 4], corners[(i + 2) % 4]
        cross.append((b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0]))
    require(all(x > 0 for x in cross), 'Convex clockwise corners required')


def orientation_permutation(record):
    """Geometry from the preexisting independent annotation, never fitted to predictions."""
    screen = record['screenCornersTLTRBRBL']
    canonical = record['canonicalCornersA8H8H1A1']
    require(record['orientation'] == 'printed-board-coordinates', 'Explicit printed-coordinate orientation required')
    for corners in [screen, canonical]:
        validate_corners(corners, record['imageSize'])
    permutations = [[(i + shift) % 4 for i in range(4)] for shift in range(4)]
    matches = [order for order in permutations if [screen[i] for i in order] == canonical]
    require(len(matches) == 1, 'Canonical orientation must be a fixed cyclic corner permutation')
    return matches[0]


def validate_prediction(prediction, record, mode, threshold):
    require(prediction.get('source') == 'real-image-inference' and prediction.get('status') == 'needs-human-review'
            and prediction.get('guidanceAllowed') is False and prediction.get('fen', 'missing') is None,
            'Prediction must remain a review-only image proposal')
    require(prediction.get('sourceSha256') == record['sourceSha256'] and prediction.get('imageSize') == record['imageSize'],
            'Prediction source identity or dimensions differ')
    require(prediction.get('modelHashes') == MODEL_HASHES, 'Classifier weights differ between evidence and contract')
    require(prediction.get('threshold') == threshold, 'Threshold differs from recorded freeze')
    require(prediction.get('calibrationMode') == mode and prediction.get('orientation') == 'white-bottom',
            'Prediction must use canonical corners without output-index inversion')
    cells = prediction.get('squares', {})
    require(set(cells) == set(SQUARES), 'Prediction needs 64 canonical squares')
    for cell in cells.values():
        raw, confidence = cell.get('rawLabel'), cell.get('confidence')
        require(isinstance(raw, str) and len(raw) == 1 and raw in '.PNBRQKpnbrqk', 'Invalid raw label')
        require(type(confidence) in (int, float) and math.isfinite(confidence) and 0 <= confidence <= 1, 'Invalid confidence')
        expected = ('empty' if raw == '.' else raw) if confidence >= threshold else 'unknown'
        require(cell.get('label') == expected, 'Acceptance differs from frozen threshold')
    # The scorer also validates every ground-truth cell and prediction label.
    return cells


def automatic_squares(geometry, prediction, record, threshold):
    require(geometry.get('sourceSha256') == record['sourceSha256'] and geometry.get('imageSize') == record['imageSize'],
            'Automatic geometry source identity differs')
    require(geometry.get('source') == 'prerecorded-image' and geometry.get('humanConfirmed') is False
            and geometry.get('fen', 'missing') is None, 'Automatic geometry must be unconfirmed')
    require(geometry.get('mode') == 'automatic-rectangle-or-grid-and-checker-heuristic', 'Manual geometry cannot enter the automatic arm')
    if geometry.get('status') == 'abstained':
        require(not geometry.get('corners') and geometry.get('squares') == [] and prediction is None
                and geometry.get('selectedGeometryMethod') is None,
                'Abstention cannot contain corners, squares or predictions')
        return None
    # Do not turn runtime errors/missing classification into a geometric abstention.
    require(geometry.get('status') == 'needs-human-confirmation' and isinstance(geometry.get('squares'), list) and len(geometry['squares']) == 64,
            'Geometry stage failed or has an unknown status; not an abstention')
    validate_corners(geometry.get('corners'), record['imageSize'])
    require(prediction is not None, 'Detected geometry lacks classifier output; classification not run')
    require(isinstance(record.get('geometryArtifactSha256'), str)
            and re.fullmatch(r'[a-f0-9]{64}', record['geometryArtifactSha256'])
            and prediction.get('geometryArtifactSha256') == record['geometryArtifactSha256']
            and prediction.get('canonicalPermutation') == orientation_permutation(record),
            'Detected-arm prediction lacks frozen geometry/orientation linkage')
    return validate_prediction(prediction, record, 'automatic-canonical-fixed-orientation', threshold)


def verify_geometry_record(geometry, saved, record):
    """Do not attach an unrelated historical run's provenance to a calibration file."""
    expected = {'id': record['id'], 'sourceSha256': record['sourceSha256'],
                'imageSize': record['imageSize'], 'timestampSeconds': record['timestampSeconds'],
                'status': geometry.get('status'), 'detected': bool(geometry.get('squares')),
                'geometryMethod': geometry.get('selectedGeometryMethod'), 'prediction': geometry.get('corners')}
    require(all(key in saved and saved[key] == value for key, value in expected.items()),
            'Calibration artifact differs from recorded geometry run')


def replay(manifest_path, evidence_root):
    root = Path(evidence_root).resolve()
    manifest_path = Path(manifest_path).resolve()
    manifest = read_json(manifest_path)
    manifest_hash = sha(manifest_path)
    controls_dir = root / 'results/video-manual-controls'
    geometry_dir = root / 'results/video-geometry'
    freeze_path = controls_dir / 'pre-inference-freeze.json'
    geometry_report_path = geometry_dir / 'evaluation.json'
    freeze, geometry_report = read_json(freeze_path), read_json(geometry_report_path)
    require(freeze['manifestSha256'] == geometry_report['manifestSha256'] == manifest_hash, 'Manifest no longer matches frozen evidence')
    require(freeze['classifierSha256'] == sha(ROOT / 'scripts/recognition/photo_pieces.py'), 'Classifier/preprocessing code drift')
    require(freeze['evaluatorSha256'] == sha(ROOT / 'scripts/recognition/evaluate_video_controls.py'), 'Manual-control generation code drift')
    require(geometry_report['algorithmSha256'] == sha(ROOT / 'scripts/vision/calibrate.py'), 'Automatic geometry code drift')
    require(geometry_report['detectorSourceSha256'] == sha(ROOT / 'native/BoardVision/BoardCandidates.swift'), 'Detector source drift')
    require(freeze['threshold'] == .95 and MANUAL_MODE in freeze['modes'], 'Unexpected classifier policy')
    require(manifest['source']['mediaSha256'] == sha(contained(root, manifest['source']['localMedia'])), 'Source video hash mismatch')
    artifacts = [{'path': str(p), 'sha256': sha(p)} for p in [manifest_path, freeze_path, geometry_report_path]]
    for name, expected in MODEL_HASHES.items():
        require(sha(root / 'models' / name) == expected, 'Local model hash mismatch: ' + name)
    automatic, manual, orientation, geometry_records = [], [], [], []
    saved_rows = geometry_report['results']
    saved_by_id = {row['id']: row for row in saved_rows}
    require(len(saved_rows) == len(saved_by_id) == len(manifest['records'])
            and set(saved_by_id) == {row['id'] for row in manifest['records']}, 'Geometry run frame set differs')
    seen = set()
    for record in manifest['records']:
        name = record['id']
        require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_-]+', name) and name not in seen, 'Invalid or duplicate record identity')
        seen.add(name)
        require(record['split'] == 'diagnostic-video', 'This legacy replay accepts diagnostic evidence only, never a held-out claim')
        require(sha(contained(root, record['image'])) == record['sourceSha256'], 'Frame hash mismatch: ' + name)
        order = orientation_permutation(record)
        orientation.append({'id': name, 'screenToCanonicalPermutation': order,
                            'source': 'preexisting printed-coordinate annotation; not prediction-selected'})
        geo_path = geometry_dir / name / 'calibration.json'
        manual_path = controls_dir / (name + '-cstr-prediction.json')
        auto_path = geometry_dir / name / 'prediction.json'
        geometry = read_json(geo_path)
        verify_geometry_record(geometry, saved_by_id[name], record)
        auto_prediction = read_json(auto_path) if auto_path.exists() else None
        manual_prediction = read_json(manual_path)
        for p in [geo_path, manual_path] + ([auto_path] if auto_prediction is not None else []):
            artifacts.append({'path': str(p), 'sha256': sha(p)})
        record = record | {'geometryArtifactSha256': sha(geo_path)}
        auto_cells = automatic_squares(geometry, auto_prediction, record, freeze['threshold'])
        manual_cells = validate_prediction(manual_prediction, record, MANUAL_MODE, freeze['threshold'])
        shared = {k: record[k] for k in ['id', 'group', 'timestampSeconds']}
        shared['truth'] = record['squares']
        automatic.append(shared | {'squares': auto_cells})
        manual.append(shared | {'squares': manual_cells})
        # Post-hoc geometry scoring; annotation never re-runs or rescues detection.
        errors = None
        if geometry.get('corners'):
            errors = [math.dist(a, b) for a, b in zip(geometry['corners'], record['screenCornersTLTRBRBL'])]
        geometry_records.append({'id': name, 'detected': auto_cells is not None,
                                 'cornerErrorsPixels': errors,
                                 'annotationUncertaintyPixels': record['cornerAnnotationUncertaintyPixels']})
    require(automatic, 'At least one paired record required')
    return {
        'schemaVersion': 1, 'mode': 'development-evidence-replay', 'heldOut': False,
        'freshInferenceRan': False, 'freshAutomaticGeometryRan': False,
        'guidanceAllowed': False, 'fen': None,
        'source': manifest['source'], 'independentSources': len({f['group'] for f in automatic}),
        'sameClassifierContract': {'modelHashes': MODEL_HASHES, 'classifierAndPreprocessSha256': freeze['classifierSha256'],
                                   'threshold': freeze['threshold'], 'automaticFramesReachingClassifier': sum(f['squares'] is not None for f in automatic),
                                   'manualFramesReachingClassifier': len(manual),
                                   'orientationIsAnnotationAssistedInBothArms': True},
        'orientation': orientation, 'geometry': geometry_records,
        'arms': {'automaticGeometry': summarize(automatic), 'annotatedCornersControl': summarize(manual)},
        'inputs': artifacts, 'evaluatorSha256': sha(__file__), 'metricsSha256': sha(Path(__file__).with_name('paired_metrics.py')),
        'limitations': [
            'Recorded existing diagnostic evidence, not a fresh same-run A/B experiment or held-out result.',
            'Automatic abstentions remain in every attempted-frame denominator; no classifier accuracy is assigned where inference did not run.',
            'Manual control supplies geometry and orientation. Existing manual predictions lack per-prediction corner hashes; their frozen generator and manifest are checked, not newly certified.',
            'Training overlap is unknown. The source has already informed error analysis. No tuning or split promotion is allowed by this replay.',
            'Fixed confidence bins describe observed correctness of uncalibrated scores; unknown truth is never scored correct or wrong.',
            'Four-second sample gaps and incomplete labels cannot establish continuous legal tracking, complete FEN, repetitions or whole-board accuracy.',
            'Prior Vision runtime failure was not retried or replaced. This evaluator imports no Vision runtime and performs no inference.',
        ],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'scripts/recognition/video-manifest.json')
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = replay(args.manifest, args.evidence_root)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write('\n')
        print(json.dumps({'output': str(args.output), 'mode': report['mode'], 'heldOut': False, 'frames': len(report['geometry'])}))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, 'Comparison not produced: ' + str(error) + '\n')
