#!/usr/bin/env python3
"""Piece-type reader v2 for a chess board shown on a screen (feasibility prototype, simulated images only).

Not wired into the app or the screen pipeline. Safety rule: a reading is only useful if it can say
"unsure" and is almost never confidently wrong, so every square that does not clearly match one
learned piece shape is returned as 'unsure'. Intended use: a guard beside the move tracker that can only
WITHHOLD advice (see `compare`); agreement with the believed position is never proof.

Method (no outside data): as v1, the shapes are learned per game from the human-reviewed start picture(s);
each later square is compared with every learned shape under a per-square gain and offset and a small shift.
v2 adds five rules on top of v1 (see docs/PIECE_CLASSIFIER.md, "v2"):
  1. Start cleanliness: the start must be explained by the reviewed position (empty squares flat, every piece
     consistent with its siblings of the same kind, white and black shapes of a kind agreeing). Otherwise the
     reader refuses to learn: state 'no-reference', every answer 'unsure' (reason 'no-reference').
  2. Thin evidence: a kind learned from fewer than EVIDENCE_MIN start squares is never named, and as a runner-up
     it must be beaten by MARGIN_THIN (its imprecise shape may fit its own pieces badly). If a kind of one colour
     was never shown, no piece of that colour is named (the missing kind could be the answer).
  3. Confirmation: a piece is named only if the previous picture's best match on that square was the same kind
     (a piece sliding across the board can sit exactly centred on a square it is only passing). Without a
     previous reading nothing is named.
  4. Picture quality: the light/dark square boundaries of the rectified board must be sharp and in place
     (blur, motion blur, a tiny board and lens bow widen or move them); otherwise every square is 'unsure'.
  5. `compare(result, believed)`: per square consistent / objection / cannot-tell and one overall verdict.
Fail-closed input handling (2026-11-17, after the review of 2026-11-17): no public function raises on bad input.
`calibrate` refuses a start it cannot use (state 'no-reference', problem 'unusable-start'); `read` answers 'unsure'
everywhere with reason 'bad-image', 'bad-corners', 'orientation-changed' (the board's screen orientation differs from
the start's) or 'read-failed'; `compare` answers 'cannot-tell' with a reason for a malformed reading or belief, a
belief that is not a full position, or a refused reading. These changes can only remove names and 'consistent'.

Runtime inputs only: pictures, the board's four corners (a8, h8, h1, a1 in image pixels), the reviewed start
position, the previous reading and, for `compare`, the believed position. The truth of a picture being read is
used ONLY by the `evaluate` subcommand, for scoring.

Library:
    cal = calibrate([(image, corners), ...], start_fen)       # cal['state'] is 'ok' or 'no-reference'; never raises
    prev = read(start_image, start_corners, cal)              # seeds the confirmation rule
    result = read(image, corners, cal, previous=prev)         # {'a1': {'label', 'reason', 'best', ...}, ...}
    verdict = compare(result, believed_placement)             # {'squares': {...}, 'verdict': ..., 'reason': ...}
    labels: 'P','N','B','R','Q','K' (white), 'p','n','b','r','q','k' (black) or 'unsure'. Never 'empty'.
CLI:
    python3 -B scripts/recognition/piece_classifier_v2.py evaluate --scenes ROOT --split NAME --out DIR
"""
import argparse
import json
import math
from pathlib import Path
import os
import sys
import time

import numpy as np
from PIL import Image

TILE = 36          # pixels per square in the internal rectified board (screen-upright)
SHIFT = 2          # compared shifts: -SHIFT..SHIFT pixels in x and y (about +-5.5 % of a square)
WIN = TILE - 2 * SHIFT
BOARD = 8 * TILE
SUPERSAMPLE_MAX = 4
PIECES = 'PNBRQKpnbrqk'
FILES = 'abcdefgh'
SQUARES = [f + str(r) for r in range(1, 9) for f in FILES]   # a1, b1, ..., h8
EDGE_HALF = 8      # half-width of the profile taken across each square boundary (rectified pixels)
LABELS = tuple(PIECES) + ('unsure',)
# per-square reasons meaning the whole picture was not read at all (input refused or the reader failed)
REFUSAL_REASONS = ('no-reference', 'bad-corners', 'bad-image', 'orientation-changed', 'read-failed')

# Decision policy (constants fitted on smoke + dev and on own-seed attack pictures; see docs/PIECE_CLASSIFIER.md).
POLICY = {
    'MASK_LO': 8.0,            # template transfer: |pixel - start background| below this = background (0-255)
    'MASK_HI': 24.0,           # ... above this = piece
    'GAIN_MIN': 0.6,           # per-square brightness gain allowed between template and picture
    'GAIN_MAX': 3.0,
    'MARGIN_MIN': 2.0,         # second-best residual / best residual must be at least this
    'FIT_MAX': 0.06,           # best mean squared residual / board contrast^2 must be at most this
    # v2
    'EVIDENCE_MIN': 2,         # start squares a kind must be learned from before it may be named
    'MARGIN_THIN': 3.0,        # a thin (under-evidenced) runner-up must fit at least this much worse
    # start: an empty square is not flat when the 98th pct of |pixel - its median| exceeds
    # START_EMPTY_SIGMAS x picture noise + START_EMPTY_FLOOR x contrast
    'START_EMPTY_SIGMAS': 8.0,
    'START_EMPTY_FLOOR': 0.12,
    # start: a piece disagrees with its same-kind siblings when its mean squared residual against their mean shape
    # exceeds START_SIBLING_SIGMAS x noise^2 + START_SIBLING_FLOOR x contrast^2 (kinds with 3 or more start
    # squares; a kind with exactly 2 is compared across square colours, which is less precise: SIBLING2 limits)
    'START_SIBLING_SIGMAS': 15.0,
    'START_SIBLING_FLOOR': 0.035,
    'START_SIBLING2_SIGMAS': 100.0,
    'START_SIBLING2_FLOOR': 0.07,
    'EDGE_STEP_MIN': 0.4,      # quality: a boundary profile counts if its step is >= this x start luminance contrast
    'EDGE_SEGMENTS_MIN': 16,   # quality: boundary segments (of 112) that must be measurable
    'BLUR_MAX': 1.7,           # quality: median boundary blur (Gaussian sigma, rectified px) in the worse direction
    'BLUR_IMAGE_MAX': 4.5,     # quality: the same blur in camera pixels
    'MISALIGN_MAX': 2.0,       # quality: 90th percentile |boundary offset| (rectified px)
}


class CalibrationError(ValueError):
    pass


# ------------------------------------------------------------------ geometry ----
def _homography(src, dst):
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.asarray(rows, float))
    h = vt[-1].reshape(3, 3)
    return h / h[2, 2]


def screen_rotation(corners):
    """corners a8,h8,h1,a1 -> (r, screen-ordered corners TL,TR,BR,BL as seen in the image).
    r = position of a8 in the screen order; the a8-up board is the screen board turned by np.rot90(k=r)."""
    c = np.asarray(corners, float)
    if c.shape != (4, 2) or not np.isfinite(c).all():
        raise ValueError('need four finite corners a8, h8, h1, a1')
    centre = c.mean(0)
    ang = np.arctan2(c[:, 1] - centre[1], c[:, 0] - centre[0])
    order = list(np.argsort(ang))                     # clockwise on screen (y down)
    start = int(np.argmin([np.linalg.norm(c[i]) for i in order]))
    order = order[start:] + order[:start]
    r = order.index(0)
    if [order[(r + k) % 4] for k in range(4)] != [0, 1, 2, 3]:
        raise ValueError('corners are not in a8, h8, h1, a1 cyclic order (mirrored?)')
    return r, c[order]


def picture_array(image):
    """An RGB PIL image or an HxWx3 array of finite values -> HxWx3 float32 array; ValueError for anything else
    (grayscale, RGBA or other modes, empty, NaN or infinite values)."""
    if isinstance(image, Image.Image):
        if image.mode != 'RGB':
            raise ValueError(f'picture mode {image.mode!r}; RGB required')
        image = np.asarray(image)
    if not isinstance(image, np.ndarray):
        raise ValueError('picture must be an RGB PIL image or an HxWx3 array')
    img = np.asarray(image, np.float32)
    if img.ndim != 3 or img.shape[2] != 3:
        raise ValueError(f'picture shape {img.shape}; HxWx3 required')
    if img.shape[0] < 2 or img.shape[1] < 2:
        raise ValueError(f'picture shape {img.shape} too small')
    if not np.isfinite(img).all():
        raise ValueError('picture has NaN or infinite values')
    return img


def rectify(image, corners):
    """Image (RGB PIL or HxWx3 array) + corners a8,h8,h1,a1 -> (board BOARDxBOARDx3 float32 screen-upright,
    inside BOARDxBOARD bool: False where the sample fell outside the image), plus rotation r."""
    img = picture_array(image)
    r, screen = screen_rotation(corners)
    h = _homography([(0, 0), (BOARD, 0), (BOARD, BOARD), (0, BOARD)], screen)
    side = float(np.mean([np.linalg.norm(screen[k] - screen[(k + 1) % 4]) for k in range(4)]))
    k = int(min(SUPERSAMPLE_MAX, max(1, math.ceil(side / BOARD - 0.05))))
    hgt, wid = img.shape[:2]
    acc = np.zeros((BOARD, BOARD, 3), np.float32)
    inside = np.ones((BOARD, BOARD), bool)
    base = np.arange(BOARD, dtype=np.float64)
    for oy in (np.arange(k) + 0.5) / k:
        for ox in (np.arange(k) + 0.5) / k:
            u, v = np.meshgrid(base + ox, base + oy)
            den = h[2, 0] * u + h[2, 1] * v + h[2, 2]
            x = (h[0, 0] * u + h[0, 1] * v + h[0, 2]) / den
            y = (h[1, 0] * u + h[1, 1] * v + h[1, 2]) / den
            inside &= (x >= 0) & (y >= 0) & (x <= wid - 1) & (y <= hgt - 1)
            xc = np.clip(x, 0, wid - 1.001)
            yc = np.clip(y, 0, hgt - 1.001)
            x0 = np.floor(xc).astype(np.int32)
            y0 = np.floor(yc).astype(np.int32)
            fx = (xc - x0)[..., None].astype(np.float32)
            fy = (yc - y0)[..., None].astype(np.float32)
            acc += (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy)
                    + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)
    return acc / (k * k), inside, r


def _screen_grid(r):
    a8up = np.array([[FILES[c] + str(8 - row) for c in range(8)] for row in range(8)], dtype=object)
    return np.rot90(a8up, -r)


def _tiles(board):
    return board.reshape(8, TILE, 8, TILE, 3).transpose(0, 2, 1, 3, 4).reshape(64, TILE, TILE, 3)


def _square_index(r):
    grid = _screen_grid(r).ravel().tolist()
    return [grid.index(s) for s in SQUARES]


def is_dark(square):
    return (FILES.index(square[0]) + int(square[1]) - 1) % 2 == 0   # a1 is dark


def placement(fen):
    rows = fen.split()[0].split('/')
    if len(rows) != 8:
        raise ValueError('eight ranks required')
    out = {}
    for i, row in enumerate(rows):
        c = 0
        for ch in row:
            if ch.isdigit():
                c += int(ch)
            elif ch in PIECES:
                out[FILES[c] + str(8 - i)] = ch
                c += 1
            else:
                raise ValueError(f'bad placement symbol {ch!r}')
        if c != 8:
            raise ValueError('eight files per rank required')
    return out


def _square_tiles_q(image, corners, lum_contrast=None):
    """-> (tiles 64 x TILE x TILE x 3 in SQUARES order, inside 64 bools, picture quality or None)."""
    board, inside, r = rectify(image, corners)
    idx = _square_index(r)
    tiles = _tiles(board)[idx]
    ins = inside.reshape(8, TILE, 8, TILE).transpose(0, 2, 1, 3).reshape(64, TILE, TILE)[idx]
    if lum_contrast is None:
        return tiles, ins.all(axis=(1, 2)), None
    _, screen = screen_rotation(corners)
    side = float(np.mean([np.linalg.norm(screen[k] - screen[(k + 1) % 4]) for k in range(4)]))
    return tiles, ins.all(axis=(1, 2)), grid_quality(board, lum_contrast, side / BOARD)


def _square_tiles(image, corners):
    tiles, inside, _ = _square_tiles_q(image, corners)
    return tiles, inside


# ------------------------------------------------------------------ picture quality ----
def grid_quality(board, lum_contrast, px_per_board_px=None):
    """Sharpness and placement of the light/dark square boundaries of a rectified (screen-order) board.
    Each internal boundary is cut into 8 segments (one per square); per pixel row across the boundary the step is
    normalised to 0..1, its spread gives a Gaussian blur estimate (sigma = sqrt(pi) * sum n(1-n)) and its centre the
    offset from where the corners put the boundary. Rows crossed by a piece are dropped (not monotone or too
    small a step). blur = median sigma in the worse direction (board pixels: detail lost relative to a square);
    blurImage = the same in camera pixels (focus); misalign = 90th pct |segment offset|."""
    lum = board.mean(axis=2).astype(np.float64)
    need = POLICY['EDGE_STEP_MIN'] * max(float(lum_contrast), 1e-6)
    sig = {0: [], 1: []}
    off = []
    for d, img in enumerate((lum, lum.T)):
        for k in range(1, 8):
            x = k * TILE
            P = img[:, x - EDGE_HALF:x + EDGE_HALF]
            left, right = P[:, :3].mean(1), P[:, -3:].mean(1)
            step = right - left
            ok = np.abs(step) >= need
            n = (P - left[:, None]) / np.where(ok, step, 1.0)[:, None]
            ok &= (n.min(1) > -0.25) & (n.max(1) < 1.25)
            nc = np.clip(n, 0, 1)
            s_est = math.sqrt(math.pi) * (nc * (1 - nc)).sum(1)
            o_est = (1 - nc).sum(1) - EDGE_HALF
            for j in range(8):
                rows = np.arange(j * TILE + 6, (j + 1) * TILE - 6)
                v = rows[ok[rows]]
                if len(v) >= 8:
                    sig[d].append(float(np.median(s_est[v])))
                    off.append(float(np.median(o_est[v])))
    segments = len(off)
    q = {'segments': segments, 'blur': None, 'blurImage': None, 'misalign': None}
    if lum_contrast < 6 or segments < POLICY['EDGE_SEGMENTS_MIN'] or not sig[0] or not sig[1]:
        q.update(ok=False, reason='boundaries-not-measurable')
        return q
    q['blur'] = round(max(float(np.median(sig[0])), float(np.median(sig[1]))), 3)
    q['misalign'] = round(float(np.percentile(np.abs(off), 90)), 3)
    if px_per_board_px is not None:
        q['blurImage'] = round(q['blur'] * px_per_board_px, 3)
    if q['blur'] > POLICY['BLUR_MAX']:
        q.update(ok=False, reason='blurred')
    elif q['blurImage'] is not None and q['blurImage'] > POLICY['BLUR_IMAGE_MAX']:
        q.update(ok=False, reason='out-of-focus')
    elif q['misalign'] > POLICY['MISALIGN_MAX']:
        q.update(ok=False, reason='grid-misaligned')
    else:
        q.update(ok=True, reason='ok')
    return q


# ------------------------------------------------------------------ matching ----
def _match(tiles, temps):
    """tiles S x TILE x TILE x 3, temps S x K x WIN x WIN x 3 -> (mean squared residual S x K under the best shift,
    gain and offset; the gain used S x K; the flat-square residual S)."""
    S, K = temps.shape[:2]
    R = temps.reshape(S, K, -1, 3)
    Rc = (R - R.mean(axis=2, keepdims=True)).reshape(S, K, -1)
    rr = np.einsum('skn,skn->sk', Rc, Rc)
    best = np.full((S, K), np.inf)
    best_gain = np.ones((S, K))
    empty_sse = np.full(S, np.inf)
    gmin, gmax = POLICY['GAIN_MIN'], POLICY['GAIN_MAX']
    for dy in range(2 * SHIFT + 1):
        for dx in range(2 * SHIFT + 1):
            O = tiles[:, dy:dy + WIN, dx:dx + WIN].reshape(S, -1, 3)
            Oc = (O - O.mean(axis=1, keepdims=True)).reshape(S, -1)
            oo = np.einsum('sn,sn->s', Oc, Oc)
            orr = np.einsum('sn,skn->sk', Oc, Rc)
            g = np.clip(orr / np.maximum(rr, 1e-9), gmin, gmax)
            sse = oo[:, None] - 2 * g * orr + g * g * rr
            better = sse < best
            best = np.where(better, sse, best)
            best_gain = np.where(better, g, best_gain)
            if dx == SHIFT and dy == SHIFT:
                empty_sse = oo
    n = WIN * WIN * 3
    return best / n, best_gain, empty_sse / n


# ------------------------------------------------------------------ calibration ----
def _start_problems(tiles, pos, dark, bg, contrast, alphas, renders, squares_of):
    """Is the start picture explained by the reviewed position? -> (problems, scores)."""
    m = TILE * 18 // 100                                          # central 64 %: coordinates sit in the corners
    inner = [tiles[i][m:TILE - m, m:TILE - m] for i, s in enumerate(SQUARES) if s not in pos]
    # picture noise from the empty squares: robust spread of neighbouring-pixel differences (a smooth glare
    # gradient barely changes it, a sharp arrow edge touches few pixels)
    diffs = np.concatenate([np.abs(np.diff(t, axis=1)).ravel() for t in inner])
    sigma = float(1.4826 * np.median(diffs) / math.sqrt(2))
    feats = {'sigma': round(sigma, 3), 'empty': [], 'sibling': {}}
    problems = []
    floor_e = POLICY['START_EMPTY_FLOOR'] * contrast
    for i, s in enumerate(SQUARES):
        if s in pos:
            continue
        t = tiles[i][m:TILE - m, m:TILE - m].reshape(-1, 3)
        dev = np.abs(t - np.median(t, axis=0)).max(axis=1)
        v = float(np.percentile(dev, 98) / (POLICY['START_EMPTY_SIGMAS'] * sigma + floor_e))
        feats['empty'].append(round(v, 3))
        if v > 1.0:
            problems.append(('empty-square-not-flat', s, round(v, 3)))
    for p, idx in squares_of.items():
        if len(idx) < 2:
            continue
        key = 'START_SIBLING' if len(idx) >= 3 else 'START_SIBLING2'
        limit = POLICY[key + '_SIGMAS'] * sigma ** 2 + POLICY[key + '_FLOOR'] * contrast ** 2
        costs = []
        for j, i in enumerate(idx):
            target = bool(dark[i])
            others = [renders[p][target][k] for k in range(len(idx)) if k != j]
            tmpl = np.mean(others, axis=0)[SHIFT:SHIFT + WIN, SHIFT:SHIFT + WIN]
            cost, _, _ = _match(tiles[i:i + 1], tmpl[None, None])
            costs.append(float(cost[0, 0] / limit))
        feats['sibling'][p] = [round(c, 3) for c in costs]
        for i, v in zip(idx, costs):
            if v > 1.0:
                problems.append(('piece-disagrees-with-siblings', SQUARES[i], round(v, 3)))
    return problems, feats


def calibrate(start_pictures, start_fen):
    """start_pictures: list of (image, corners) of the human-reviewed start position. Returns templates of every
    piece kind present at the start, rendered onto light and dark squares, the evidence (start squares) per kind and
    state 'ok', or state 'no-reference' when the start picture is not clean enough to learn from.
    Never raises: input that cannot be used at all (v1 raised CalibrationError) gives state 'no-reference' with the
    single problem ('unusable-start', why) and no templates."""
    try:
        return _calibrate(start_pictures, start_fen)
    except Exception as e:  # fail closed: any failure is a refused start
        return {'kinds': [], 'evidence': {}, 'state': 'no-reference',
                'problems': [('unusable-start', f'{type(e).__name__}: {e}')], 'policy': dict(POLICY)}


def _calibrate(start_pictures, start_fen):
    start_pictures = list(start_pictures or [])
    if not start_pictures:
        raise CalibrationError('no start picture')
    pos = placement(start_fen)
    if not pos:
        raise CalibrationError('no pieces in the start position')
    rotations = {screen_rotation(corners)[0] for _, corners in start_pictures}
    if len(rotations) != 1:
        raise CalibrationError('start pictures disagree on the board orientation')
    tile_sets = []
    for image, corners in start_pictures:
        tiles, inside = _square_tiles(image, corners)
        if not inside.all():
            raise CalibrationError('start picture: board not fully inside the image')
        tile_sets.append(tiles)
    tiles = np.mean(tile_sets, axis=0)
    dark = np.array([is_dark(s) for s in SQUARES])
    empty = np.array([s not in pos for s in SQUARES])
    bg = {}
    for parity in (False, True):
        sel = empty & (dark == parity)
        if sel.sum() < 2:
            raise CalibrationError('start position needs at least two empty squares of each colour')
        m = TILE * 15 // 100
        bg[parity] = np.median(tiles[sel][:, m:TILE - m, m:TILE - m].reshape(-1, 3), axis=0)
    contrast = float(np.sqrt(np.mean((bg[True] - bg[False]) ** 2)))
    if not contrast > 4.0:
        raise CalibrationError('light and dark squares indistinguishable at the start')
    lum_contrast = float(abs(bg[True].mean() - bg[False].mean()))
    lo, hi = POLICY['MASK_LO'], POLICY['MASK_HI']
    renders = {p: {False: [], True: []} for p in PIECES}
    squares_of = {p: [] for p in PIECES}
    alphas = {}
    for i, s in enumerate(SQUARES):
        if s not in pos:
            continue
        t = tiles[i]
        src = bool(dark[i])
        alpha = np.clip((np.abs(t - bg[src]).max(axis=2) - lo) / (hi - lo), 0, 1)
        alphas[i] = alpha
        squares_of[pos[s]].append(i)
        for target in (False, True):
            renders[pos[s]][target].append(t + (1 - alpha[..., None]) * (bg[target] - bg[src]))
    kinds = [p for p in PIECES if renders[p][False]]
    templates = np.zeros((2, len(kinds), WIN, WIN, 3), np.float32)
    for k, p in enumerate(kinds):
        for target in (False, True):
            templates[int(target), k] = np.mean(renders[p][target], axis=0)[SHIFT:SHIFT + WIN, SHIFT:SHIFT + WIN]
    problems, feats = _start_problems(tiles, pos, dark, bg, contrast, alphas, renders,
                                       {p: v for p, v in squares_of.items() if v})
    return {'kinds': kinds, 'templates': templates, 'bg': np.stack([bg[False], bg[True]]),
            'contrast': contrast, 'lumContrast': lum_contrast, 'startPictures': len(start_pictures),
            'rotation': rotations.pop(),
            'evidence': {p: len(squares_of[p]) for p in kinds},
            'state': 'no-reference' if problems else 'ok', 'problems': problems, 'startScores': feats,
            'policy': dict(POLICY)}


# ------------------------------------------------------------------ reading ----
def _blank(reason, detail=None):
    rec = {'label': 'unsure', 'reason': reason, 'best': None, 'second': None, 'margin': None, 'fit': None,
           'gain': None}
    if detail is not None:
        rec['detail'] = detail
    return rec


def _all_blank(reason, error=None):
    detail = None if error is None else f'{type(error).__name__}: {error}'
    return {s: _blank(reason, detail) for s in SQUARES}


def read_tiles(tiles, inside, cal, previous=None, quality=None):
    """tiles: 64 x TILE x TILE x 3 in SQUARES order, inside: 64 bools, previous: the reading of the previous picture
    (or None: nothing can be confirmed), quality: grid_quality of this picture (None = not measured).
    Returns {square: {...}}."""
    if cal.get('state') != 'ok':
        return {s: _blank('no-reference') for s in SQUARES}
    kinds, temps = cal['kinds'], cal['templates']
    dark = np.array([is_dark(s) for s in SQUARES]).astype(int)
    cost_k, gain_k, empty_c = _match(tiles, temps[dark])
    gmin, gmax = POLICY['GAIN_MIN'], POLICY['GAIN_MAX']
    scale = cal['contrast'] ** 2
    evidence = cal.get('evidence') or {}
    thin = np.array([evidence.get(k, 0) < POLICY['EVIDENCE_MIN'] for k in kinds] + [False])
    incomplete = {True: any(p not in kinds for p in 'PNBRQK'), False: any(p not in kinds for p in 'pnbrqk')}
    poor_picture = quality is not None and not quality.get('ok')
    labels = list(kinds) + ['empty']
    out = {}
    for i, s in enumerate(SQUARES):
        cost = np.concatenate([cost_k[i], [empty_c[i]]])
        order = np.argsort(cost)
        b = order[0]
        c1 = cost[b]
        c2 = cost[order[1]] if len(order) > 1 else np.inf
        rest = np.ones(len(cost), bool)
        rest[b] = False
        solid_rest, thin_rest = rest & ~thin, rest & thin
        m_solid = float(cost[solid_rest].min() / max(c1, 1e-6)) if solid_rest.any() else np.inf
        m_thin = float(cost[thin_rest].min() / max(c1, 1e-6)) if thin_rest.any() else np.inf
        margin = float(c2 / max(c1, 1e-6))
        fit = float(c1 / scale)
        label = labels[b]
        rec = {'best': label, 'second': labels[order[1]] if len(order) > 1 else None,
               'margin': round(margin, 3) if np.isfinite(margin) else None,
               'fit': round(fit, 4) if np.isfinite(fit) else None,
               'gain': round(float(gain_k[i, b]), 3) if b < len(kinds) else None,
               'marginSolid': round(m_solid, 3) if np.isfinite(m_solid) else None,
               'marginThin': round(m_thin, 3) if np.isfinite(m_thin) else None}
        if not inside[i]:
            rec.update(label='unsure', reason='outside-image')
        elif not np.isfinite(c1):
            rec.update(label='unsure', reason='no-candidate')
        elif poor_picture:
            rec.update(label='unsure', reason='poor-picture')
        elif fit > POLICY['FIT_MAX']:
            rec.update(label='unsure', reason='poor-fit')
        elif m_solid < POLICY['MARGIN_MIN']:
            rec.update(label='unsure', reason='small-margin')
        elif m_thin < POLICY['MARGIN_THIN']:
            rec.update(label='unsure', reason='thin-runner-up')
        elif label == 'empty':
            rec.update(label='unsure', reason='no-piece-seen')   # occupancy is the square reader's call, not ours
        elif not (gmin < gain_k[i, b] < gmax):
            rec.update(label='unsure', reason='gain-at-limit')
        elif thin[b]:
            rec.update(label='unsure', reason='thin-evidence')
        elif incomplete[label.isupper()]:
            rec.update(label='unsure', reason='kind-set-incomplete')
        elif previous is None or (previous.get(s) or {}).get('best') != label:
            rec.update(label='unsure', reason='unconfirmed')
        else:
            rec.update(label=label, reason='ok')
        out[s] = rec
    return out


def read(image, corners, cal, previous=None):
    """Read one picture. previous = the reading of the picture before it (see read_tiles).
    Never raises: a missing or refused start, bad corners, a bad picture, a board orientation that differs from the
    start's, or any failure inside the reader gives 'unsure' on every square (reasons in REFUSAL_REASONS)."""
    if not isinstance(cal, dict) or cal.get('state') != 'ok':
        return _all_blank('no-reference')
    try:
        r, _ = screen_rotation(corners)
    except Exception as e:
        return _all_blank('bad-corners', e)
    if r != cal.get('rotation'):
        return _all_blank('orientation-changed')
    try:
        img = picture_array(image)
    except Exception as e:
        return _all_blank('bad-image', e)
    try:
        tiles, inside, q = _square_tiles_q(img, corners, cal['lumContrast'])
        return read_tiles(tiles, inside, cal, previous if isinstance(previous, dict) else None, q)
    except Exception as e:  # fail closed
        return _all_blank('read-failed', e)


def _compare_problem(result, believed):
    if not isinstance(result, dict) or any(not isinstance(result.get(s), dict) or result[s].get('label') not in LABELS
                                           for s in SQUARES):
        return 'malformed-result'
    if not isinstance(believed, dict):
        return 'malformed-belief'
    return None


def _piece_ok(p):
    return isinstance(p, str) and len(p) == 1 and p in PIECES


def compare(result, believed):
    """Guard output. result: a reading; believed: {square: piece} the app believes, the FULL position (absent =
    empty). Per square: 'objection' when the reader confidently names something other than what is believed
    (including a piece on a square believed empty), 'consistent' when it names the believed piece, else 'cannot-tell'.
    verdict: 'objection' if any square objects, else 'consistent' if every believed piece is confirmed and every
    square believed empty was seen without a piece ('no-piece-seen'), else 'cannot-tell'. 'reason' says why.
    Never raises: a malformed reading, or a belief that is not a dict, gives 'cannot-tell' on every square. A belief
    with malformed entries (keys off the board, values that are not piece letters: 'malformed-belief'; such a square
    is 'cannot-tell'), a refused reading, or a belief that is not a full position (not exactly one king of each
    colour: 'partial-belief') gives 'cannot-tell' overall unless some square objects (an objection is kept: it can
    only withhold).
    Agreement is never proof that the position is right: use only 'objection'; treat 'consistent' as no information."""
    problem = _compare_problem(result, believed)
    if problem:
        return {'squares': {s: 'cannot-tell' for s in SQUARES}, 'verdict': 'cannot-tell', 'reason': problem}
    squares = {}
    for s in SQUARES:
        lab = result[s]['label']
        want = believed.get(s)
        if lab == 'unsure':
            squares[s] = 'cannot-tell'
        elif want is not None and not _piece_ok(want):
            squares[s] = 'cannot-tell'
        elif lab == want:
            squares[s] = 'consistent'
        else:
            squares[s] = 'objection'
    refused = sorted({result[s].get('reason') for s in SQUARES} & set(REFUSAL_REASONS))
    pieces = list(believed.values())
    if any(v == 'objection' for v in squares.values()):
        verdict, reason = 'objection', 'objection'
    elif refused:
        verdict, reason = 'cannot-tell', 'reading-refused: ' + ', '.join(refused)
    elif any(k not in SQUARES or not _piece_ok(v) for k, v in believed.items()):
        verdict, reason = 'cannot-tell', 'malformed-belief'
    elif pieces.count('K') != 1 or pieces.count('k') != 1:
        verdict, reason = 'cannot-tell', 'partial-belief'
    elif any(result[s].get('reason') != 'no-piece-seen' for s in SQUARES if s not in believed):
        verdict, reason = 'cannot-tell', 'believed-empty-square-unclear'
    elif believed and all(squares[s] == 'consistent' for s in believed):
        verdict, reason = 'consistent', 'every-square-agrees'
    else:
        verdict, reason = 'cannot-tell', 'unsure-squares'
    return {'squares': squares, 'verdict': verdict, 'reason': reason}


def policy():
    return {'TILE': TILE, 'SHIFT': SHIFT, 'SUPERSAMPLE_MAX': SUPERSAMPLE_MAX, 'EDGE_HALF': EDGE_HALF, **POLICY}


# ------------------------------------------------------------------ evaluation (truth used here only) ----
def _condition(game, frame):
    d = frame['disturbance']
    if d.get('hand'):
        return 'hand'
    if d.get('glare'):
        return 'glare'
    if d.get('banding'):
        return 'banding'
    stress = (game.get('stress') or {}).get('name')
    if stress and stress != 'baseline':
        return stress
    return 'clean'


def _blur_bucket(frame):
    s = frame['scene'].get('blurSigma') or 0
    return 'blur<0.5' if s < 0.5 else ('blur0.5-1' if s < 1.0 else 'blur>=1')


def _start_count(game):
    frames = game['frames']
    if 'positionIndex' in frames[0]:
        return sum(1 for f in frames if f['positionIndex'] == 0)
    return 1


def _swap_cases(pos, rng, limit):
    occ = sorted(pos)
    pairs = [(a, b) for i, a in enumerate(occ) for b in occ[i + 1:]
             if pos[a] != pos[b] and pos[a].isupper() == pos[b].isupper() and is_dark(a) == is_dark(b)]
    if len(pairs) > limit:
        pairs = [pairs[j] for j in sorted(rng.choice(len(pairs), limit, replace=False))]
    return pairs


def _verdict(cmp, squares):
    """Guard verdict restricted to the changed squares: noticed / missed / unsure."""
    v = [cmp['squares'][s] for s in squares]
    if 'objection' in v:
        return 'noticed'
    if all(x == 'consistent' for x in v):
        return 'missed'
    return 'unsure'


def _settled(tiles, inside, cal, q):
    """Reading of a picture whose previous picture showed the same thing (a settled scene seen twice)."""
    return read_tiles(tiles, inside, cal, read_tiles(tiles, inside, cal, None, q), q)


def _load(path):
    return np.asarray(Image.open(path).convert('RGB'), np.float32)


def evaluate(scenes, split, out, swaps_per_picture=3, limit_games=None, dump_squares=False):
    if 'held' in split:
        raise SystemExit('held-out splits are off limits for this prototype')
    scenes = Path(scenes)
    games = [g for g in json.loads((scenes / 'truth/games.json').read_text())['games'] if g['split'] == split]
    if limit_games:
        games = games[:limit_games]
    rng = np.random.default_rng(12345)
    rows, swap_rows, timing, starts, mid, alarms = [], [], [], [], [], []
    for game in games:
        n_start = _start_count(game)
        frames = game['frames']
        start = [(_load(scenes / f['file']), f['corners']) for f in frames[:n_start]]
        cal = calibrate(start, game['startFen'])
        if 'lumContrast' not in cal:                            # unusable start (v1 raised CalibrationError)
            starts.append({'game': game['id'], 'ok': False, 'reason': cal['problems'][0][1]})
            continue
        starts.append({'game': game['id'], 'ok': cal['state'] == 'ok', 'state': cal['state'],
                       'problems': cal['problems'][:12], 'kinds': ''.join(cal['kinds'])})
        prev = read(start[-1][0], start[-1][1], cal)
        prev_fen = frames[n_start - 1]['fen']
        for f in frames[n_start:]:
            img = _load(scenes / f['file'])
            t0 = time.perf_counter()
            tiles, inside, q = _square_tiles_q(img, f['corners'], cal['lumContrast'])
            t1 = time.perf_counter()
            turned = screen_rotation(f['corners'])[0] != cal.get('rotation')     # as read(): refuse a turned board
            if turned:
                res = _all_blank('orientation-changed')
            else:
                res = read_tiles(tiles, inside, cal, prev, q) if cal['state'] == 'ok' else read_tiles(tiles, inside, cal)
            t2 = time.perf_counter()
            prev = res
            truth = placement(f['fen'])
            if f.get('transition'):
                before = placement(prev_fen)
                for s in SQUARES:
                    lab = res[s]['label']
                    mid.append({'g': game['id'], 'i': f['index'], 's': s, 'r': lab,
                                'ok': lab == 'unsure' or lab in (before.get(s), truth.get(s))})
                continue
            prev_fen = f['fen']
            timing.append(((t1 - t0) * 1000, (t2 - t1) * 1000))
            cond, blur = _condition(game, f), _blur_bucket(f)
            for s in SQUARES:
                rec = res[s]
                row = {'g': game['id'], 'i': f['index'], 's': s, 't': truth.get(s, 'empty'), 'r': rec['label'],
                       'cond': cond, 'blur': blur, 'reason': rec['reason']}
                if dump_squares:
                    row.update(best=rec['best'], second=rec['second'], margin=rec['margin'], fit=rec['fit'],
                               gain=rec['gain'], q=q)
                rows.append(row)
            alarms.append({'g': game['id'], 'i': f['index'], 'cond': cond, 'verdict': compare(res, truth)['verdict']})
            # constructed swaps and substitutions (claim = the true position); each is read as a settled scene
            for a, b in ([] if turned else _swap_cases(truth, rng, swaps_per_picture)):
                ia, ib = SQUARES.index(a), SQUARES.index(b)
                sw = tiles.copy()
                sw[ia], sw[ib] = tiles[ib], tiles[ia]
                r_sw = _settled(sw, inside, cal, q)
                sub = tiles.copy()
                sub[ib] = tiles[ia]
                r_sub = _settled(sub, inside, cal, q)
                swap_rows.append({'g': game['id'], 'i': f['index'], 'a': a, 'b': b, 'pa': truth[a], 'pb': truth[b],
                                  'cond': cond,
                                  'swap': _verdict(compare(r_sw, truth), (a, b)),
                                  'swapReads': [r_sw[a]['label'], r_sw[b]['label']],
                                  'sub': _verdict(compare(r_sub, truth), (b,)),
                                  'subRead': r_sub[b]['label'],
                                  'baseline': _verdict(compare(res, truth), (a, b))})
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    doc = {'schema': 'piece-classifier-v2-eval', 'split': split, 'note': 'simulated images only; true corners',
           'policy': policy(), 'starts': starts, 'timingMs': timing, 'squares': rows, 'swaps': swap_rows,
           'midMove': mid, 'alarms': alarms}
    (out / f'{split}.json').write_text(json.dumps(doc))
    print(summarise(doc))
    return doc


def _count(rows, key=None):
    groups = {}
    for r in rows:
        if r['t'] == 'empty':
            continue
        k = key(r) if key else 'all'
        c = groups.setdefault(k, {'n': 0, 'correct': 0, 'wrongType': 0, 'wrongEmpty': 0, 'unsure': 0})
        c['n'] += 1
        if r['r'] == r['t']:
            c['correct'] += 1
        elif r['r'] == 'unsure':
            c['unsure'] += 1
        elif r['r'] == 'empty':
            c['wrongEmpty'] += 1
        else:
            c['wrongType'] += 1
    return groups


def summarise(doc):
    rows = doc['squares']
    st = doc['starts']
    lines = [f"split {doc['split']}: starts accepted {sum(s['ok'] for s in st)} of {len(st)}"
             f" (no-reference {sum(s.get('state') == 'no-reference' for s in st)})"]
    for name, key in (('all', None), ('type', lambda r: r['t'].upper() + ('w' if r['t'].isupper() else 'b')),
                      ('condition', lambda r: r['cond']), ('blur', lambda r: r['blur'])):
        for k, c in sorted(_count(rows, key).items()):
            lines.append(f"  {name:9s} {k:20s} correct {c['correct']} of {c['n']}, wrong {c['wrongType'] + c['wrongEmpty']}"
                         f" (type {c['wrongType']}, empty {c['wrongEmpty']}), unsure {c['unsure']}")
    reasons = {}
    for r in rows:
        if r['t'] != 'empty' and r['r'] == 'unsure':
            reasons[r['reason']] = reasons.get(r['reason'], 0) + 1
    lines.append(f"  unsure reasons (occupied): {dict(sorted(reasons.items(), key=lambda kv: -kv[1]))}")
    empties = [r for r in rows if r['t'] == 'empty']
    lines.append(f"  empty squares named as a piece: {sum(r['r'] in PIECES for r in empties)} of {len(empties)}")
    mid = doc.get('midMove') or []
    if mid:
        lines.append(f"  mid-move pictures: squares {len(mid)}, named {sum(r['r'] != 'unsure' for r in mid)},"
                     f" confident-wrong {sum(not r['ok'] for r in mid)}")
    al = doc.get('alarms') or []
    lines.append(f"  unchanged pictures: verdict objection (false alarm) {sum(a['verdict'] == 'objection' for a in al)}"
                 f" of {len(al)}, consistent {sum(a['verdict'] == 'consistent' for a in al)},"
                 f" cannot-tell {sum(a['verdict'] == 'cannot-tell' for a in al)}")
    sw = doc['swaps']
    for kind in ('swap', 'sub', 'baseline'):
        tally = {v: sum(1 for x in sw if x[kind] == v) for v in ('noticed', 'missed', 'unsure')}
        lines.append(f"  {kind:8s} noticed {tally['noticed']} / missed {tally['missed']} / unsure {tally['unsure']}"
                     f" of {len(sw)}")
    if doc['timingMs']:
        t = np.asarray(doc['timingMs'])
        lines.append(f"  ms per picture: rectify+quality median {np.median(t[:, 0]):.0f}, read median {np.median(t[:, 1]):.0f},"
                     f" total p95 {np.percentile(t.sum(1), 95):.0f}")
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    ev = sub.add_parser('evaluate')
    ev.add_argument('--scenes', required=True)
    ev.add_argument('--split', required=True)
    ev.add_argument('--out', required=True)
    ev.add_argument('--swaps-per-picture', type=int, default=3)
    ev.add_argument('--limit-games', type=int)
    ev.add_argument('--dump-squares', action='store_true')
    args = ap.parse_args()
    if os.environ.get('ORCHESTRATOR_HELDOUT_RUN'):
        raise SystemExit('ORCHESTRATOR_HELDOUT_RUN is set; this prototype never runs on held-out data')
    evaluate(args.scenes, args.split, args.out, args.swaps_per_picture, args.limit_games, args.dump_squares)


if __name__ == '__main__':
    main()
