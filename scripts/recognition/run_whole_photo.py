#!/usr/bin/env python3
"""Private noncommercial local bridge. Fixed model/runner; no user-selected commands.

The existing Swift runner compiles/loads and predicts three times per request.
Cold latency can be seconds. The failed numerical gate remains failed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time
import zipfile

from PIL import Image
from whole_photo import preprocess, proposal

MODEL = Path.home() / 'Library/Developer/ChessCompanionEvaluation/models/chessq-lite'
RELEASE = 'cq-vit-s-644-v4-seed2-coreml-fp16-r1'
MODEL_SHA = '091e8a9f22a517322eccd7bf8292a76fd653f9f913ff15d2eb9e8d914e959016'
# This is our already-compiled native/PhotoRecognition/RunModel.swift, not upstream code.
RUNNER_SHA = '5599cad2f70435d5688657624220c3a695a99a59ce777c9b1750c08eda9463f8'
MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 25_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def verify_model():
    archive = MODEL / (RELEASE + '.mlpackage.zip')
    package = MODEL / (RELEASE + '.mlpackage')
    runner = MODEL / 'run-model'
    if archive.is_symlink() or digest(archive) != MODEL_SHA:
        raise ValueError('Pinned model archive hash mismatch')
    if runner.is_symlink() or digest(runner) != RUNNER_SHA:
        raise ValueError('Local runner hash mismatch; review and rebuild provenance explicitly')
    expected = set()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            relative = Path(member.filename)
            if relative.is_absolute() or '..' in relative.parts or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError('Unsafe model archive member')
            if member.is_dir():
                continue
            if not relative.parts or relative.parts[0] != package.name:
                raise ValueError('Unexpected model archive root')
            target = MODEL / relative
            if any(p.is_symlink() for p in [target, *target.parents]) or not target.is_file():
                raise ValueError('Unsafe extracted model path')
            with bundle.open(member) as handle:
                expected_hash = hashlib.file_digest(handle, 'sha256').hexdigest()
            if digest(target) != expected_hash:
                raise ValueError('Extracted model differs from pinned archive')
            expected.add(target.relative_to(package).as_posix())
    actual = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
    if not expected or actual != expected or any(p.is_symlink() for p in package.rglob('*')):
        raise ValueError('Unexpected extracted model contents')
    return runner, package


def recognize(image):
    started = time.perf_counter()
    if image.is_symlink() or not image.is_file() or not 0 < image.stat().st_size <= MAX_BYTES:
        raise ValueError('Invalid image size or path')
    with Image.open(image) as source:
        w, h = source.size
        if source.format not in {'JPEG', 'PNG', 'WEBP'}:
            raise ValueError('Only JPEG, PNG and WebP are supported')
        if not (0 < w <= 8192 and 0 < h <= 8192 and w * h <= MAX_PIXELS):
            raise ValueError('Image dimensions exceed limit')
        if getattr(source, 'n_frames', 1) != 1:
            raise ValueError('Animated images are not supported')
        source.verify()
    runner, package = verify_model()
    verified_ms = (time.perf_counter() - started) * 1000
    tensor, preprocess_ms = preprocess(image)
    tensor_path, logits_path = image.parent / 'input.f32', image.parent / 'logits.json'
    tensor.astype('<f4').tofile(tensor_path)
    # Inherit the Node-owned process group so cancellation kills Python and CoreML.
    env = dict(os.environ)
    env.pop('CHESS_COREML_CPU_DIAGNOSTIC', None)
    try:
        subprocess.run([str(runner), str(package), str(tensor_path), str(logits_path)],
                       check=True, timeout=110, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env=env)
        if logits_path.stat().st_size > 128 * 1024:
            raise ValueError('Native output exceeded limit')
        native = json.loads(logits_path.read_text())
        result = proposal(image, native['logits'])
        result['timing'] = {'verificationMs': verified_ms, 'preprocessMs': preprocess_ms,
                            'compileAndLoadMs': native['compileAndLoadMs'],
                            'inferenceMs': native['inferenceMs'],
                            'totalMs': (time.perf_counter() - started) * 1000}
        result['provenance'] = {'modelSha256': MODEL_SHA, 'runnerSha256': RUNNER_SHA,
                                'license': 'PolyForm Noncommercial 1.0.0',
                                'computeUnits': native['computeUnits'],
                                'purpose': 'private-noncommercial-evaluation',
                                'numericalValidationPassed': False}
        return result
    finally:
        tensor_path.unlink(missing_ok=True)
        logits_path.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(recognize(args.image), allow_nan=False))
    except Exception as error:
        # No image content, file paths or subprocess internals in HTTP-facing errors.
        parser.exit(1, f'Local recognition failed ({type(error).__name__}).\n')
