#!/usr/bin/env python3
"""Export our fixed synthetic classic appearance assets; never read corpus truth.

This is a build-time asset step only. The phone uses the bundled JSON and Swift;
it does not require Python, Pillow, a Mac service, or a neural model at runtime.
"""
import base64
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
import numpy as np
import appearance
import recognize


def main():
    templates, backgrounds, energies = recognize._templates()
    encoded = np.rint(templates * 255).astype(np.uint8).tobytes()
    payload = {
        'schemaVersion': 1, 'asset': 'owned-synthetic-classic-features-v1',
        'labels': recognize.LABELS, 'shape': [2, 13, 28, 28, 3],
        'encoding': 'base64-uint8-row-major-RGB',
        'featuresBase64': base64.b64encode(encoded).decode('ascii'),
        'featuresSha256': hashlib.sha256(encoded).hexdigest(),
        'backgrounds': backgrounds.tolist(), 'edgeEnergies': energies.tolist(),
        'sourceHashes': {name: hashlib.sha256((ROOT / 'scripts/simulation' / name).read_bytes()).hexdigest()
                         for name in ('appearance.py', 'recognize.py')},
        'provenance': 'Original local vector silhouettes, classic style only. No per-frame image, FEN, scene or evaluation truth is included.',
        'preprocessing': 'Pillow GaussianBlur(0.5), bilinear 64-to-32 resize, crop two-pixel border, RGB uint8 features.'}
    destination = Path(__file__).resolve().parent / 'Assets/classic-templates-v1.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + '\n')
    print(json.dumps({'path': str(destination), 'featureBytes': len(encoded), 'featuresSha256': payload['featuresSha256']}))


if __name__ == '__main__':
    main()
