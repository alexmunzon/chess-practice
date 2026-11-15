#!/usr/bin/env python3
"""Generator-only FEN-to-pixels renderer; never used by the recognizer.

JSON on stdin: {renders:[{fen, scene, output}]} (or one render object).
Outputs contain pixels only: RGB PNG without text, EXIF, or FEN metadata.
"""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from appearance import BOARD_ORIGIN, MARKERS, PANEL_COLOR, PANEL_SIZE, TILE_SIZE, render_tile


def labels_from_fen(fen):
    rows = fen.split()[0].split('/')
    labels = []
    if len(rows) != 8:
        raise ValueError('Eight placement ranks required')
    for row in rows:
        expanded = []
        for symbol in row:
            if symbol in '12345678':
                expanded.extend('.' * int(symbol))
            elif symbol in 'PNBRQKpnbrqk':
                expanded.append(symbol)
            else:
                raise ValueError('Invalid placement symbol')
        if len(expanded) != 8:
            raise ValueError('Eight placement squares required')
        labels.extend(expanded)
    return labels


def transform_coefficients(quad):
    """Inverse homography for Pillow: output scene -> canonical panel."""
    points = np.asarray(quad, dtype=float)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError('Finite four-corner scene quad required')
    rows, values = [], []
    for (x, y), (u, v) in zip(points, [(0, 0), (640, 0), (640, 640), (0, 640)]):
        rows.extend([[x, y, 1, 0, 0, 0, -x*u, -y*u], [0, 0, 0, x, y, 1, -x*v, -y*v]])
        values.extend([u, v])
    return tuple(np.linalg.solve(np.asarray(rows), np.asarray(values)))


def render(fen, scene):
    panel = Image.new('RGB', (PANEL_SIZE, PANEL_SIZE), PANEL_COLOR)
    for index, label in enumerate(labels_from_fen(fen)):
        row, column = divmod(index, 8)
        tile = render_tile(label, dark=bool((row+column) % 2), style=scene.get('style', 'classic'))
        panel.paste(tile, (BOARD_ORIGIN[0]+column*TILE_SIZE, BOARD_ORIGIN[1]+row*TILE_SIZE))
    draw = ImageDraw.Draw(panel)
    for marker in MARKERS:
        x, y = marker['center']
        radius = marker['radius']
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=marker['rgb'])
    # Optional palette variation changes only board colors, never marker IDs.
    if scene.get('boardVariation'):
        pixels = np.array(panel)
        board = pixels[64:576, 64:576]
        board[:] = np.clip(board.astype(float)*np.array([1.03, .98, .94]), 0, 255).astype(np.uint8)
        panel = Image.fromarray(pixels, 'RGB')
    for item in scene.get('occlusions', []):
        draw = ImageDraw.Draw(panel)
        draw.rectangle(item['box'], fill=tuple(item.get('color', [130, 109, 97])))
    quad = scene.get('quad', [[64, 64], [704, 64], [704, 704], [64, 704]])
    image = panel.transform((768, 768), Image.Transform.PERSPECTIVE, transform_coefficients(quad),
                            Image.Resampling.BILINEAR, fillcolor=(62, 66, 70))
    image = ImageEnhance.Brightness(image).enhance(float(scene.get('brightness', 1)))
    if scene.get('blur', 0):
        image = image.filter(ImageFilter.GaussianBlur(float(scene['blur'])))
    return image


def main():
    request = json.load(sys.stdin)
    renders = request.get('renders', [request])
    results = []
    for item in renders:
        output = Path(item['output'])
        output.parent.mkdir(parents=True, exist_ok=True)
        render(item['fen'], item.get('scene', {})).save(output, format='PNG', optimize=False)
        results.append({'sourceSha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                        'imageSize': [768, 768]})
    print(json.dumps(results))


if __name__ == '__main__':
    main()
