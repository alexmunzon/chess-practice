#!/usr/bin/env python3
"""Reviewed manual geometry with image-order crops; never confirmed chess state.

The pinned model card specifies chesscog occupancy/piece crops:
https://huggingface.co/cstr/chess-board-photo-onnx/blob/4690fd5418ff7c405a76d1c156077ecd865ac053/README.md
Intended classes, RGB normalization and image-order crops were corroborated at:
https://github.com/CrispStrobe/CrispChess/blob/0d01798daf9661076675f8505b4cc6995a6529da/tool/board_photo/py/crops.py
Upstream's resize/warp sampling differs from this existing Pillow classifier.
The app source is not bound to the pinned model revision. This adapter has no
measured recognition accuracy or upstream numerical crop parity.
It changes square indexing after inference, without rotating the crop coordinate frame.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import re
import struct
import tempfile

from PIL import Image, ImageOps
from photo_pieces import Classifier, CLASSES, MODEL_HASHES, placement

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('manual_board_calibration', ROOT / 'scripts/vision/calibrate.py')
calibration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calibration)

MODEL_ROOT = Path.home() / 'Library/Developer/ChessCompanionEvaluation/models'
MODEL_REVISION = '4690fd5418ff7c405a76d1c156077ecd865ac053'
PIPELINE_VERSION = 'image-order-crops-v1'
THRESHOLD = .95
MAX_BYTES = 8 * 1024 * 1024
MAX_DIMENSION = 8192
MAX_PIXELS = 25_000_000
REQUIRED = {'sourceSha256', 'imageSize', 'corners', 'topLeftSquare', 'geometryReviewed'}
TOP_LEFT_SQUARES = ('a8', 'h8', 'h1', 'a1')
SQUARES = tuple(file + str(rank) for rank in range(8, 0, -1) for file in 'abcdefgh')


def canonical_square(row, column, top_left):
    """Map image-grid indices only; do not rotate pixels or directional crops."""
    if top_left == 'a8':
        r, c = row, column
    elif top_left == 'h8':
        r, c = column, 7 - row
    elif top_left == 'h1':
        r, c = 7 - row, 7 - column
    elif top_left == 'a1':
        r, c = 7 - column, row
    else:
        raise ValueError('Explicit top-left square required')
    return 'abcdefgh'[c] + str(8 - r)


def validate_request(request, *, recognition=False):
    """Pure JSON schema/geometry boundary shared with the Node adapter."""
    if not isinstance(request, dict) or not REQUIRED <= request.keys() or set(request) - REQUIRED - {'calibrationId'}:
        raise ValueError('Invalid manual calibration request fields')
    if not isinstance(request['sourceSha256'], str) or not re.fullmatch('[a-f0-9]{64}', request['sourceSha256']):
        raise ValueError('A lowercase source SHA256 is required')
    size = request['imageSize']
    if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or not 0 < n <= MAX_DIMENSION for n in size) or size[0] * size[1] > MAX_PIXELS:
        raise ValueError('Invalid oriented image dimensions')
    corners = request['corners']
    if not isinstance(corners, list) or len(corners) != 4 or any(
        not isinstance(point, list) or len(point) != 2 or any(type(n) not in (int, float) or not math.isfinite(n) for n in point)
        for point in corners
    ):
        raise ValueError('Four finite image-order corners required')
    points = calibration.validate(corners, *size)
    # Convex cyclic permutations are not interchangeable for directional crops.
    if not (points[0][1] + points[1][1] < points[2][1] + points[3][1] and
            points[0][0] + points[3][0] < points[1][0] + points[2][0]):
        raise ValueError('Corners must stay in image order TL, TR, BR, BL')
    if request['topLeftSquare'] not in TOP_LEFT_SQUARES:
        raise ValueError('Explicit top-left square required')
    if type(request['geometryReviewed']) is not bool or request['geometryReviewed'] is not recognition:
        raise ValueError('Preview is unreviewed; recognition requires explicit geometry review')
    if recognition:
        if not isinstance(request.get('calibrationId'), str) or not re.fullmatch('[a-f0-9]{64}', request['calibrationId']):
            raise ValueError('Reviewed calibration identity required')
    elif 'calibrationId' in request:
        raise ValueError('A preview creates a new calibration identity')
    return {**request, 'imageSize': list(size), 'corners': points}


def calibration_id(request):
    """Node/Python shared digest: UTF-8 prefix then eight big-endian float64s."""
    width, height = request['imageSize']
    prefix = f"manual-image-calibration-v1\n{request['sourceSha256']}\n{width},{height}\n{request['topLeftSquare']}\n"
    coordinates = [0.0 if number == 0 else float(number) for point in request['corners'] for number in point]
    return hashlib.sha256(prefix.encode('utf8') + struct.pack('>8d', *coordinates)).hexdigest()


def image_identity(image):
    path = Path(image)
    if path.is_symlink() or not path.is_file():
        raise ValueError('A regular local image is required')
    with path.open('rb') as handle:
        data = handle.read(MAX_BYTES + 1)
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError('Image must be at most 8 MiB')
    with Image.open(io.BytesIO(data)) as source:
        width, height = source.size
        if source.format not in ('JPEG', 'PNG', 'WEBP') or getattr(source, 'n_frames', 1) != 1:
            raise ValueError('One JPEG, PNG or WebP frame is required')
        if max(width, height) > MAX_DIMENSION or width * height > MAX_PIXELS:
            raise ValueError('Image dimensions exceed limits')
        source.verify()
    with Image.open(io.BytesIO(data)) as source:
        size = list(ImageOps.exif_transpose(source).size)
    return hashlib.sha256(data).hexdigest(), size


def checked_request(image, request, *, recognition=False):
    clean = validate_request(request, recognition=recognition)
    digest, size = image_identity(image)
    if digest != clean['sourceSha256'] or size != clean['imageSize']:
        raise ValueError('Calibration does not match the source image and orientation')
    identity = calibration_id(clean)
    if recognition and clean['calibrationId'] != identity:
        raise ValueError('Image, corners or orientation changed after geometry review')
    return clean, identity


def _manual_geometry(image, request):
    # Temporary derivatives are private to this operation and removed before return.
    with tempfile.TemporaryDirectory(prefix='chess-manual-geometry-') as output:
        result = calibration.calibrate(image, output, corners=request['corners'],
                                       orientation='white-bottom', confirmed=False)
    if result['sourceSha256'] != request['sourceSha256'] or result['imageSize'] != request['imageSize']:
        raise ValueError('Source image changed during calibration')
    return result


def preview(image, request):
    clean, identity = checked_request(image, request)
    geometry = _manual_geometry(image, clean)
    squares = [{'square': canonical_square(cell['row'], cell['column'], clean['topLeftSquare']),
                'sourcePolygon': cell['sourcePolygon']} for cell in geometry['squares']]
    return {'schemaVersion': 1, 'source': 'manual-image-calibration',
            'sourceSha256': clean['sourceSha256'], 'imageSize': clean['imageSize'],
            'corners': clean['corners'], 'topLeftSquare': clean['topLeftSquare'],
            'calibrationId': identity, 'status': 'needs-geometry-review',
            'squares': squares, 'fen': None, 'guidanceAllowed': False}


def _validate_prediction(result, request):
    if not isinstance(result, dict) or result.get('schemaVersion') != 1 or result.get('source') != 'real-image-inference' or result.get('sourceSha256') != request['sourceSha256'] or result.get('imageSize') != request['imageSize']:
        raise ValueError('Classifier returned a foreign image result')
    if result.get('threshold') != THRESHOLD or result.get('modelHashes') != MODEL_HASHES or result.get('status') != 'needs-human-review' or result.get('fen') is not None or result.get('guidanceAllowed') is not False:
        raise ValueError('Classifier returned an invalid review-only result')
    elapsed = result.get('elapsedMs')
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError('Invalid classifier timing')
    cells = result.get('squares')
    if not isinstance(cells, dict) or set(cells) != set(SQUARES):
        raise ValueError('Classifier must return 64 explicit squares')
    for cell in cells.values():
        if not isinstance(cell, dict) or not isinstance(cell.get('rawLabel'), str) or len(cell['rawLabel']) != 1 or cell['rawLabel'] not in '.' + CLASSES:
            raise ValueError('Invalid raw piece label')
        score = cell.get('confidence')
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid classifier score')
        label = ('empty' if cell['rawLabel'] == '.' else cell['rawLabel']) if score >= THRESHOLD else 'unknown'
        if cell.get('label') != label:
            raise ValueError('Classifier threshold contract changed')
    if result.get('rawPlacement') != placement([cells[key]['rawLabel'] for key in SQUARES]):
        raise ValueError('Classifier placement does not match its squares')


def recognition(image, request, *, classifier=None):
    """The optional classifier is a local test seam, never a request parameter."""
    clean, identity = checked_request(image, request, recognition=True)
    geometry = {'sourceSha256': clean['sourceSha256'], 'imageSize': clean['imageSize'],
                'corners': clean['corners'], 'orientation': 'white-bottom',
                'mode': 'manual-image-order-corners', 'humanConfirmed': True}
    # White-bottom disables the legacy index inversion only. Corners and pixels
    # remain in image order; explicit canonical mapping happens below.
    result = (classifier if classifier is not None else Classifier(MODEL_ROOT)).recognize(image, geometry, THRESHOLD)
    _validate_prediction(result, clean)
    remapped = {canonical_square(index // 8, index % 8, clean['topLeftSquare']): dict(result['squares'][key])
                for index, key in enumerate(SQUARES)}
    squares = {key: remapped[key] for key in SQUARES}
    raw = placement([cell['rawLabel'] for cell in squares.values()])
    unknown = sum(cell['label'] == 'unknown' for cell in squares.values())
    return {**result, 'squares': squares, 'rawPlacement': raw,
            'completeAcceptedPlacement': raw if unknown == 0 else None, 'unknownSquares': unknown,
            'model': 'cstr/chess-board-photo-onnx', 'modelRevision': MODEL_REVISION,
            'calibrationId': identity, 'topLeftSquare': clean['topLeftSquare'],
            'pipelineVersion': PIPELINE_VERSION, 'geometryHumanReviewed': True,
            'orientation': 'explicit-top-left-square',
            'status': 'needs-human-review', 'fen': None, 'guidanceAllowed': False,
            'limitations': list(result.get('limitations', [])) + [
                'Manual geometry and explicit orientation are not automatic board recognition.',
                'Image-order adapter recognition accuracy and upstream numerical crop parity remain unvalidated.',
                'Geometry review does not confirm pieces or historical game state.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preview', 'recognize'))
    parser.add_argument('image', type=Path)
    parser.add_argument('request', type=Path)
    args = parser.parse_args()
    try:
        if args.request.stat().st_size > 8192:
            raise ValueError('Manual request exceeds limit')
        request = json.loads(args.request.read_text())
        function = preview if args.mode == 'preview' else recognition
        print(json.dumps(function(args.image, request), allow_nan=False))
    except Exception as error:
        parser.exit(1, f'Manual photo workflow failed ({type(error).__name__}).\n')
