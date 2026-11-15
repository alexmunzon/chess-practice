#!/usr/bin/env python3
"""Compare native and frozen Python outputs on REUSED synthetic image bytes.

This runner reads only the pixel index and image bytes, never evaluator truth.
Its Python dependency is a development test oracle, not an iPhone dependency.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
import recognize


def compare(binary, corpus):
    pixels = Path(corpus).resolve() / 'pixels'
    index = json.loads((pixels / 'index.json').read_text())
    if index.get('mode') != 'synthetic-pixels' or index.get('schemaVersion') != 1:
        raise ValueError('Expected existing synthetic pixel corpus')
    paths = []
    for frame in index['frames']:
        if set(frame) != {'id', 'file', 'timestampMs'}:
            raise ValueError('Pixel index contains unsupported frame metadata')
        path = pixels / frame['file']
        if path.is_symlink() or path.resolve().parent != pixels or path.suffix != '.png':
            raise ValueError('Expected direct PNG corpus member')
        paths.append(path)
    assets = Path(__file__).resolve().parent / 'Assets/classic-templates-v1.json'
    process = subprocess.run([str(binary), '--assets', str(assets), *map(str, paths)],
                             capture_output=True, text=True, timeout=120)
    if process.returncode:
        raise RuntimeError(process.stderr)
    results = [json.loads(line) for line in process.stdout.splitlines()]
    if len(results) != len(paths):
        raise ValueError('Native result count mismatch')
    frames = []
    maximum_delta = {'templateRmse': 0.0, 'runnerUpMargin': 0.0, 'borderRmse': 0.0, 'edgeEnergyRatio': 0.0}
    for item, path, native in zip(index['frames'], paths, results):
        data = path.read_bytes()
        oracle = recognize.recognize_bytes(data)
        if native['sourceSha256'] != hashlib.sha256(data).hexdigest() or native['imageSize'] != oracle['imageSize']:
            raise ValueError('Native result source identity mismatch')
        if native['fen'] is not None or native['guidanceAllowed'] is not False or native['status'] != 'needs-human-review':
            raise ValueError('Native review gate failed')
        disagreement = []
        for square, expected in oracle['squares'].items():
            actual = native['squares'][square]
            for key in ('rawLabel', 'label', 'confidence', 'rawLabelAvailable', 'abstentionReasons'):
                if actual[key] != expected[key]:
                    disagreement.append({'square': square, 'field': key, 'native': actual[key], 'python': expected[key]})
            for field in maximum_delta:
                a, b = actual[field], expected[field]
                if a is None and b is None:
                    continue
                if a is None or b is None:
                    disagreement.append({'square': square, 'field': field, 'native': a, 'python': b})
                else:
                    maximum_delta[field] = max(maximum_delta[field], abs(a-b))
        frames.append({'id': item['id'], 'sourceSha256': native['sourceSha256'],
                       'geometryAgrees': native['geometry']['available'] == oracle['geometry']['available'],
                       'unknownSquares': native['unknownSquares'], 'pythonUnknownSquares': oracle['unknownSquares'],
                       'nativeElapsedMs': native['elapsedMs'], 'pythonElapsedMs': oracle['elapsedMs'],
                       'disagreements': disagreement})
    total = sum(len(frame['disagreements']) for frame in frames)
    return {'schemaVersion': 1, 'mode': 'reused-synthetic-native-port-conformance',
            'host': platform.platform(), 'deviceTested': False, 'freshHeldoutEvaluation': False,
            'nativeImplementationVersion': results[0]['nativeImplementationVersion'],
            'comparedFrames': len(frames), 'comparedSquares': len(frames)*64,
            'decisionDisagreements': total, 'allGeometryAgrees': all(frame['geometryAgrees'] for frame in frames),
            'maximumMetricAbsoluteDifferences': maximum_delta,
            'medianNativeElapsedMs': statistics.median(frame['nativeElapsedMs'] for frame in frames),
            'passed': total == 0 and all(frame['geometryAgrees'] for frame in frames),
            'limitations': ['Existing corpus was reused; this measures port conformance, not new recognition accuracy.',
                            'Mac CPU execution is not an iPhone build, performance measurement, camera or glasses test.',
                            'PNG corpus decoding does not establish JPEG/ICC/WebP numerical equivalence with Pillow.'],
            'frames': frames}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    report = compare(args.binary, args.corpus)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'frames'}))
    raise SystemExit(0 if report['passed'] else 1)
