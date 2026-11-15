#!/usr/bin/env python3
"""Pixel-only synthetic baseline. No scene, FEN, seed, manifest or filename logic.

Visible colored fiducials locate a deliberately rendered panel. Classic tile
templates are fixed assets, not labels supplied for the input frame. This is
not a physical-board recognizer and its binary confidence is not a probability.
"""
import argparse
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import time
import warnings

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from appearance import BOARD_ORIGIN, MARKERS, PANEL_SIZE, TILE_SIZE, render_tile

LABELS = '.PNBRQKpnbrqk'
MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 25_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

# Fixed development policy. Do not tune these from future evaluation labels.
MAX_CHROMA_DISTANCE = .12
MIN_MARKER_PIXELS = 16
MAX_TILE_RMSE = .055
MIN_TEMPLATE_MARGIN = .012
MAX_BORDER_RMSE = .045
MIN_EDGE_RATIO = .40


def _component(mask):
    ys, xs = np.nonzero(mask)
    if len(xs) < MIN_MARKER_PIXELS or len(xs) > min(20_000, mask.size * .03):
        raise ValueError('missing-or-excessive-marker-pixels')
    remaining = set(zip(ys.tolist(), xs.tolist()))
    components = []
    while remaining:
        start = remaining.pop()
        found, stack = [start], [start]
        while stack:
            y, x = stack.pop()
            for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
                point = (y+dy, x+dx)
                if point in remaining:
                    remaining.remove(point); stack.append(point); found.append(point)
        components.append(found)
    components.sort(key=len, reverse=True)
    largest = components[0]
    if len(largest) < MIN_MARKER_PIXELS or (len(components)>1 and len(components[1]) >= len(largest)*.2):
        raise ValueError('ambiguous-marker-components')
    points = np.asarray(largest, dtype=float)
    lo, hi = points.min(axis=0), points.max(axis=0)
    height, width = hi-lo+1
    if min(lo) <= 0 or hi[0] >= mask.shape[0]-1 or hi[1] >= mask.shape[1]-1:
        raise ValueError('clipped-marker')
    if not .4 <= width/height <= 2.5 or len(points)/(width*height) < .45:
        raise ValueError('unsupported-marker-shape')
    y, x = points.mean(axis=0)
    return [float(x), float(y)], len(largest)


def _markers(image):
    scale = min(1.0, 1280/max(image.size))
    size = (max(1,round(image.width*scale)), max(1,round(image.height*scale)))
    small = image if scale == 1 else image.resize(size, Image.Resampling.BILINEAR)
    pixels = np.asarray(small, dtype=np.float32)
    chroma = pixels / np.maximum(pixels.sum(axis=2, keepdims=True), 1)
    saturated = pixels.max(axis=2)-pixels.min(axis=2) > 70
    detected = []
    for marker in MARKERS:
        color = np.asarray(marker['rgb'], dtype=float)
        distance = np.linalg.norm(chroma-color/color.sum(), axis=2)
        point, count = _component(saturated & (distance < MAX_CHROMA_DISTANCE))
        detected.append({'name':marker['name'], 'center':[(point[0]+.5)*image.width/size[0]-.5,
                                                        (point[1]+.5)*image.height/size[1]-.5],
                         'detectedPixels':count})
    return detected


def _rectify(image, detected):
    points = np.asarray([item['center'] for item in detected], dtype=float)
    edges = np.roll(points,-1,axis=0)-points
    cross = edges[:,0]*np.roll(edges[:,1],-1)-edges[:,1]*np.roll(edges[:,0],-1)
    if not (cross > 100).all():
        raise ValueError('invalid-marker-order')
    rows, values = [], []
    for marker, (x,y) in zip(MARKERS, points):
        u, v = np.asarray(marker['center']) / PANEL_SIZE
        rows.extend([[u,v,1,0,0,0,-u*x,-v*x],[0,0,0,u,v,1,-u*y,-v*y]])
        values.extend([x,y])
    matrix = np.append(np.linalg.solve(np.asarray(rows),np.asarray(values)),1).reshape(3,3)
    corners = []
    for u,v in ((0,0),(1,0),(1,1),(0,1)):
        p = matrix @ [u,v,1]
        if not np.isfinite(p).all() or abs(p[2]) < 1e-9:
            raise ValueError('invalid-panel-projection')
        point = p[:2]/p[2]
        if point[0]<-1 or point[1]<-1 or point[0]>image.width+1 or point[1]>image.height+1:
            raise ValueError('panel-outside-image')
        corners.append(point.tolist())
    matrix[:,:2] /= PANEL_SIZE
    panel = image.transform((PANEL_SIZE,PANEL_SIZE),Image.Transform.PERSPECTIVE,
                            tuple(matrix.flatten()[:8]),Image.Resampling.BILINEAR)
    return panel, corners


def _border(tile):
    # The fixed silhouettes stay inside an eight-pixel margin. Exclude the
    # outermost pixels, where perspective interpolation can mix adjacent tiles.
    mask = np.zeros((TILE_SIZE,TILE_SIZE),dtype=bool)
    mask[3:7,3:-3] = True; mask[-7:-3,3:-3] = True
    mask[3:-3,3:7] = True; mask[3:-3,-7:-3] = True
    return tile[mask]


def _features(tile):
    image = Image.fromarray(np.clip(tile,0,255).astype(np.uint8),'RGB')
    image = image.filter(ImageFilter.GaussianBlur(.5)).resize((32,32),Image.Resampling.BILINEAR)
    return np.asarray(image,dtype=float)[2:-2,2:-2]/255


def _edge_energy(features):
    gray = features.mean(axis=2)
    return float(np.mean(np.diff(gray,axis=0)**2)+np.mean(np.diff(gray,axis=1)**2))


@lru_cache(maxsize=1)
def _templates():
    templates, backgrounds, energies = [], [], []
    for dark in (False,True):
        images = [np.asarray(render_tile(label,dark=dark,style='classic'),dtype=float) for label in LABELS]
        features = np.asarray([_features(tile) for tile in images])
        templates.append(features)
        backgrounds.append(np.median(_border(images[0]),axis=0))
        energies.append([_edge_energy(feature) for feature in features])
    return np.asarray(templates), np.asarray(backgrounds), np.asarray(energies)


def _tiles(panel):
    pixels = np.asarray(panel,dtype=float)
    x,y = BOARD_ORIGIN
    return [pixels[y+r*TILE_SIZE:y+(r+1)*TILE_SIZE,x+c*TILE_SIZE:x+(c+1)*TILE_SIZE]
            for r in range(8) for c in range(8)]


def _classify(panel):
    templates, expected_backgrounds, template_energies = _templates()
    tiles = _tiles(panel)
    parity = [(i//8+i%8)%2 for i in range(64)]
    observed = np.asarray([np.median([np.median(_border(tile),axis=0) for tile,dark in zip(tiles,parity) if dark==side],axis=0)
                           for side in (0,1)])
    gain = (observed[0]-observed[1])/(expected_backgrounds[0]-expected_backgrounds[1])
    offset = observed[0]-gain*expected_backgrounds[0]
    if not np.isfinite(gain).all() or not ((gain>=.4)&(gain<=1.6)).all() or not (np.abs(offset)<=80).all():
        raise ValueError('unsupported-board-palette-or-lighting')
    squares = {}
    for index,(tile,dark) in enumerate(zip(tiles,parity)):
        corrected = (tile-offset)/gain
        features = _features(corrected)
        residuals = np.sqrt(np.mean((templates[dark]-features)**2,axis=(1,2,3)))
        order = np.argsort(residuals,kind='stable');best=int(order[0]);second=int(order[1])
        residual,margin = float(residuals[best]),float(residuals[second]-residuals[best])
        border_residual = float(np.sqrt(np.mean(((_border(corrected)-expected_backgrounds[dark])/255)**2)))
        label = LABELS[best]
        edge_ratio = None if label=='.' else _edge_energy(features)/max(float(template_energies[dark,best]),1e-9)
        reasons = []
        if residual>MAX_TILE_RMSE:reasons.append('template-residual')
        if margin<MIN_TEMPLATE_MARGIN:reasons.append('ambiguous-template')
        if border_residual>MAX_BORDER_RMSE:reasons.append('occluded-or-inconsistent-background')
        if edge_ratio is not None and edge_ratio<MIN_EDGE_RATIO:reasons.append('insufficient-edge-detail')
        accepted = not reasons
        square = 'abcdefgh'[index%8]+str(8-index//8)
        squares[square] = {'rawLabel':label,'label':('empty' if label=='.' else label) if accepted else 'unknown',
                           'confidence':1 if accepted else 0,'rawLabelAvailable':True,
                           'templateRmse':residual,'runnerUpMargin':margin,'borderRmse':border_residual,
                           'edgeEnergyRatio':edge_ratio,'abstentionReasons':reasons}
    return squares, {'gain':gain.tolist(),'offset':offset.tolist()}


def _unknown(reason):
    return {'abcdefgh'[i%8]+str(8-i//8):{'rawLabel':'.','label':'unknown','confidence':0,
            'rawLabelAvailable':False,'templateRmse':None,'runnerUpMargin':None,'borderRmse':None,
            'edgeEnergyRatio':None,'abstentionReasons':[reason]} for i in range(64)}


def _placement(squares):
    rows = []
    for rank in '87654321':
        row, empty = '', 0
        for file in 'abcdefgh':
            label = squares[file+rank]['rawLabel']
            if label=='.':empty+=1
            else:
                if empty:row+=str(empty);empty=0
                row+=label
        rows.append(row+(str(empty) if empty else ''))
    return '/'.join(rows)


def recognize_bytes(data):
    started = time.perf_counter()
    if not isinstance(data,bytes) or not 0<len(data)<=MAX_BYTES:
        raise ValueError('Expected at most 8 MiB of image bytes')
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ('PNG','JPEG','WEBP') or getattr(source,'n_frames',1)!=1 or max(source.size)>8192 or source.width*source.height>MAX_PIXELS:
                raise ValueError('Unsupported image format or dimensions')
            oriented = ImageOps.exif_transpose(source)
            # Match visible pixels: dropping alpha could reveal a board that
            # the review image hides. Palette PNG transparency also counts.
            if 'A' in oriented.getbands() or 'transparency' in oriented.info:
                if oriented.convert('RGBA').getchannel('A').getextrema()[0] != 255:
                    raise ValueError('Nonopaque images are unsupported')
            image = oriented.convert('RGB')
    decoded_at = time.perf_counter()
    markers, corners, normalization, reason = [], None, None, None
    try:
        markers = _markers(image)
        panel, corners = _rectify(image,markers)
    except (ValueError,np.linalg.LinAlgError) as error:
        reason = str(error);panel = None
    geometry_at = time.perf_counter()
    if panel is None:
        squares = _unknown('geometry-unavailable')
    else:
        try:squares,normalization = _classify(panel)
        except ValueError as error:reason=str(error);squares=_unknown('unsupported-panel-appearance')
    finished = time.perf_counter()
    return {'schemaVersion':1,'source':'synthetic-pixel-inference','model':'synthetic-screen-template-v1',
            'pipelineVersion':'visible-markers-v1','sourceSha256':hashlib.sha256(data).hexdigest(),'imageSize':list(image.size),
            'status':'needs-human-review','fen':None,'guidanceAllowed':False,'threshold':.95,
            'confidenceMeaning':'Binary fixed-template acceptance indicator (1 accepted, 0 abstained), not calibrated probability.',
            'rawPlacement':_placement(squares),'rawPlacementAvailable':all(cell['rawLabelAvailable'] for cell in squares.values()),
            'squares':squares,'unknownSquares':sum(cell['label']=='unknown' for cell in squares.values()),
            'geometry':{'available':panel is not None,'markers':markers,'panelCorners':corners,'failureReason':reason},
            'photometricNormalization':normalization,
            'fixedPolicy':{'maxTileRmse':MAX_TILE_RMSE,'minTemplateMargin':MIN_TEMPLATE_MARGIN,'maxBorderRmse':MAX_BORDER_RMSE,'minEdgeRatio':MIN_EDGE_RATIO},
            'elapsedMs':(finished-started)*1000,
            'timing':{'decodeMs':(decoded_at-started)*1000,'geometryMs':(geometry_at-decoded_at)*1000,
                      'classificationMs':(finished-geometry_at)*1000,'totalMs':(finished-started)*1000},
            'limitations':['Synthetic marker-equipped rendered panels only; not physical pieces, glasses or camera evidence.',
                          'Only fixed classic templates are supported; unknown appearance, occlusion or poor pixels may abstain and can still cause errors.',
                          'Raw labels are nearest templates, not confirmed state. Without usable pixels, dot raw labels are placeholders, never empty-square observations.',
                          'No historical state, legal-move repair, temporal fill-in, FEN, seed or scene metadata enters recognition.']}


def recognize(image):
    return recognize_bytes(Path(image).read_bytes())


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path)
    args=parser.parse_args()
    try:print(json.dumps(recognize(args.image),allow_nan=False))
    except Exception as error:parser.exit(1,f'Synthetic pixel recognition failed ({type(error).__name__}).\n')
