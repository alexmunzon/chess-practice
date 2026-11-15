#!/usr/bin/env python3
"""Frozen automatic localization on genuine-video frames, scored only afterward.

No annotated corner, orientation, piece label or prior-frame result enters the
calibrator. This is a diagnostic, not a required-success or accuracy claim.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default=str(ROOT / 'scripts/recognition/video-manifest.json'))
    parser.add_argument('--media-root', required=True)
    parser.add_argument('--detector', required=True)
    parser.add_argument('--output', required=True, help='Outside repository: contains licensed source derivatives')
    parser.add_argument('--report', help='Optional media-free benchmark JSON destination')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error('Media output must be outside the repository')
    source = ROOT / 'scripts/vision/calibrate.py'
    algorithm_sha = sha(source)
    spec = importlib.util.spec_from_file_location('calibrate_video', source)
    calibrator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(calibrator)
    manifest = json.loads(Path(args.manifest).read_text())
    results = []
    for record in manifest['records']:
        image = Path(args.media_root) / record['image']
        if sha(image) != record['sourceSha256']:
            parser.error(f"Source hash mismatch: {record['id']}")
        start = time.monotonic()
        # Intentionally pass pixels only; never leak annotation geometry.
        prediction = calibrator.calibrate(image, output / record['id'], detector=args.detector)
        elapsed = time.monotonic() - start
        if prediction['imageSize'] != record['imageSize']:
            parser.error(f"Oriented dimensions mismatch: {record['id']}")
        assert prediction['fen'] is None and not prediction['humanConfirmed']
        assert prediction['orientation'] is None
        uncertainty = record['cornerAnnotationUncertaintyPixels']
        result = dict(id=record['id'], sourceSha256=record['sourceSha256'],
                      timestampSeconds=record['timestampSeconds'], imageSize=record['imageSize'],
                      status=prediction['status'], detected=bool(prediction['squares']),
                      geometryMethod=prediction['selectedGeometryMethod'],
                      proposalCount=len(prediction['proposals']), elapsedSeconds=elapsed,
                      annotationUncertaintyPixels=uncertainty,
                      annotationHumanConfirmed=record['humanConfirmed'],
                      prediction=prediction.get('corners'),
                      meanCornerErrorPixels=None, maxCornerErrorPixels=None,
                      meanErrorBeyondAnnotationUncertaintyPixels=None,
                      grossFalseDetection=False, outcome='abstained')
        # Ground truth is first used below, after automatic calibration returns.
        truth = np.asarray(record['screenCornersTLTRBRBL'], dtype=float)
        square_width = float(np.linalg.norm(np.roll(truth, -1, axis=0) - truth, axis=1).mean() / 8)
        result['meanAnnotatedSquareSidePixels'] = square_width
        if result['detected']:
            assert len(prediction['squares']) == 64
            errors = np.linalg.norm(np.asarray(prediction['corners']) - truth, axis=1)
            excess = np.maximum(0, errors - uncertainty)
            gross = bool(excess.max() > square_width / 2)
            result.update(cornerErrorsPixels=errors.tolist(),
                          meanCornerErrorPixels=float(errors.mean()),
                          maxCornerErrorPixels=float(errors.max()),
                          meanErrorBeyondAnnotationUncertaintyPixels=float(excess.mean()),
                          maxErrorBeyondAnnotationUncertaintyPixels=float(excess.max()),
                          grossFalseDetection=gross,
                          outcome='gross-false-detection' if gross else (
                              'within-annotation-uncertainty' if errors.max() <= uncertainty else 'geometry-error'))
        results.append(result)
        print(json.dumps(result), flush=True)
    if sha(source) != algorithm_sha:
        raise RuntimeError('Calibration source changed during evaluation')
    report = dict(schemaVersion=1, purpose='Frozen automatic board localization diagnostic; not piece recognition',
                  algorithmSha256=algorithm_sha,
                  detectorSourceSha256=sha(ROOT / 'native/BoardVision/BoardCandidates.swift'),
                  detectorBinarySha256=sha(args.detector), manifestSha256=sha(args.manifest),
                  source=manifest['source'], split='diagnostic-video',
                  annotationConvention='screenCornersTLTRBRBL; EXIF-oriented pixels; no symmetry matching',
                  methodology='Automatic image-only calibration first; annotation geometry scored post hoc. No manual fallback or detector tuning.',
                  grossFalseDetectionDefinition='Maximum corner error after subtracting annotation uncertainty exceeds half the mean annotated square side. Diagnostic criterion, not a deployed confidence gate.',
                  limitations=['Five correlated frames from one video, not independent games.',
                               'Annotations are assistant visual estimates, not user-confirmed; uncertainty is not a statistical confidence interval.',
                               'No piece/FEN, live capture, wearable-view or hardware accuracy established.',
                               'Runtime includes file I/O and derivative generation, not end-to-end live latency.'],
                  summary=dict(frames=len(results), detections=sum(r['detected'] for r in results),
                               abstentions=sum(not r['detected'] for r in results),
                               grossFalseDetections=sum(r['grossFalseDetection'] for r in results),
                               withinAnnotationUncertainty=sum(r['outcome']=='within-annotation-uncertainty' for r in results)),
                  results=results)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'evaluation.json').write_text(json.dumps(report, indent=2) + '\n')
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
