#!/usr/bin/env python3
"""Piece-type reader v1 for a chess board shown on a screen (feasibility prototype, simulated images only).

Not wired into the app or the screen pipeline. Safety rule: a reading is only useful if it can say
"unsure" and is almost never confidently wrong, so every square that does not clearly match one
learned piece shape is returned as 'unsure'.

Method (no outside data): screen pieces are rendered images, so the shapes are learned per game from
the human-reviewed start picture(s), where the rules of chess fix every piece's identity. Each later
picture is rectified with the board's four corners, each square is compared with every learned shape
(rendered onto that square's light or dark background) under a per-square brightness gain and colour
offset, allowing a small shift. The best match wins only if it beats the second best by a margin and
its absolute fit is good; otherwise 'unsure'.

Runtime inputs only: pictures, the board's four corners (a8, h8, h1, a1 in image pixels, pixel centres
at integers, the same contract as the scene truth and the pipeline), and the reviewed start position.
The truth of a picture being read is used ONLY by the `evaluate` subcommand, for scoring.

Library:
    cal = calibrate([(image, corners), ...], start_fen)   # reviewed start picture(s)
    result = read(image, corners, cal)                    # {'a1': {'label', 'reason', ...}, ...}
    labels: 'P','N','B','R','Q','K' (white), 'p','n','b','r','q','k' (black) or 'unsure'. The reader never
    claims a square is empty: when "no piece" fits best it says 'unsure' (reason 'no-piece-seen'), because
    occupancy belongs to the square reader (occupancy_classifier_v3) and a hand can hide a piece completely.
CLI:
    python3 -B scripts/recognition/piece_classifier_v1.py evaluate --scenes ROOT --split NAME --out DIR
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

# Decision policy (constants fitted on smoke + dev only; see docs/PIECE_CLASSIFIER.md).
POLICY = {
    'MASK_LO': 8.0,            # template transfer: |pixel - start background| below this = background (0-255)
    'MASK_HI': 24.0,           # ... above this = piece
    'GAIN_MIN': 0.6,           # per-square brightness gain allowed between template and picture
    'GAIN_MAX': 3.0,           # (1.7 on the first dev run abstained on 339 squares, all correct at the limit)
    'MARGIN_MIN': 2.0,         # second-best residual / best residual must be at least this
    'FIT_MAX': 0.06,           # best mean squared residual / board contrast^2 must be at most this
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
    # a8,h8,h1,a1 is itself a cyclic order; it must agree with the screen's clockwise order.
    r = order.index(0)
    if [order[(r + k) % 4] for k in range(4)] != [0, 1, 2, 3]:
        raise ValueError('corners are not in a8, h8, h1, a1 cyclic order (mirrored?)')
    return r, c[order]


def rectify(image, corners):
    """Image (PIL or HxWx3 array) + corners a8,h8,h1,a1 -> (board BOARDxBOARDx3 float32 screen-upright,
    inside BOARDxBOARD bool: False where the sample fell outside the image), plus rotation r."""
    img = image if isinstance(image, np.ndarray) else np.asarray(image.convert('RGB'), np.float32)
    img = img.astype(np.float32, copy=False)
    r, screen = screen_rotation(corners)
    # corners are pixel centres; board pixel edges 0..BOARD map onto them
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
    """8x8 array of square names laid out as on screen (row 0 = top of the picture)."""
    a8up = np.array([[FILES[c] + str(8 - row) for c in range(8)] for row in range(8)], dtype=object)
    return np.rot90(a8up, -r)


def _tiles(board):
    return board.reshape(8, TILE, 8, TILE, 3).transpose(0, 2, 1, 3, 4).reshape(64, TILE, TILE, 3)


def _square_index(r):
    """For each square in SQUARES order, its index in the screen tile order."""
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


def _square_tiles(image, corners):
    board, inside, r = rectify(image, corners)
    idx = _square_index(r)
    tiles = _tiles(board)[idx]                                   # SQUARES order
    ins = inside.reshape(8, TILE, 8, TILE).transpose(0, 2, 1, 3).reshape(64, TILE, TILE)[idx]
    return tiles, ins.all(axis=(1, 2))


# ------------------------------------------------------------------ calibration ----
def calibrate(start_pictures, start_fen):
    """start_pictures: list of (image, corners) of the human-reviewed start position. Returns templates of every
    piece kind present at the start, rendered onto light and dark squares."""
    if not start_pictures:
        raise CalibrationError('no start picture')
    pos = placement(start_fen)
    tile_sets = []
    for image, corners in start_pictures:
        tiles, inside = _square_tiles(image, corners)
        if not inside.all():
            raise CalibrationError('start picture: board not fully inside the image')
        tile_sets.append(tiles)
    tiles = np.mean(tile_sets, axis=0)                           # average of the reviewed start pictures
    dark = np.array([is_dark(s) for s in SQUARES])
    empty = np.array([s not in pos for s in SQUARES])
    bg = {}
    for parity in (False, True):
        sel = empty & (dark == parity)
        if sel.sum() < 2:
            raise CalibrationError('start position needs at least two empty squares of each colour')
        # inner 70 % of empty squares, median per channel
        m = TILE * 15 // 100
        bg[parity] = np.median(tiles[sel][:, m:TILE - m, m:TILE - m].reshape(-1, 3), axis=0)
    contrast = float(np.sqrt(np.mean((bg[True] - bg[False]) ** 2)))
    if not contrast > 4.0:
        raise CalibrationError('light and dark squares indistinguishable at the start')
    lo, hi = POLICY['MASK_LO'], POLICY['MASK_HI']
    renders = {p: {False: [], True: []} for p in PIECES}
    for i, s in enumerate(SQUARES):
        if s not in pos:
            continue
        t = tiles[i]
        src = bool(dark[i])
        alpha = np.clip((np.abs(t - bg[src]).max(axis=2) - lo) / (hi - lo), 0, 1)[..., None]
        for target in (False, True):
            renders[pos[s]][target].append(t + (1 - alpha) * (bg[target] - bg[src]))
    kinds = [p for p in PIECES if renders[p][False]]
    templates = np.zeros((2, len(kinds), WIN, WIN, 3), np.float32)
    for k, p in enumerate(kinds):
        for target in (False, True):
            templates[int(target), k] = np.mean(renders[p][target], axis=0)[SHIFT:SHIFT + WIN, SHIFT:SHIFT + WIN]
    return {'kinds': kinds, 'templates': templates, 'bg': np.stack([bg[False], bg[True]]),
            'contrast': contrast, 'startPictures': len(start_pictures), 'policy': dict(POLICY)}


# ------------------------------------------------------------------ reading ----
def read_tiles(tiles, inside, cal):
    """tiles: 64 x TILE x TILE x 3 in SQUARES order, inside: 64 bools. Returns {square: {...}}."""
    kinds, temps = cal['kinds'], cal['templates']
    dark = np.array([is_dark(s) for s in SQUARES]).astype(int)
    R = temps[dark].reshape(64, len(kinds), -1, 3)               # 64 x K x WIN*WIN x 3
    Rc = R - R.mean(axis=2, keepdims=True)
    Rc = Rc.reshape(64, len(kinds), -1)
    rr = np.einsum('skn,skn->sk', Rc, Rc)
    best = np.full((64, len(kinds)), np.inf)
    best_gain = np.ones((64, len(kinds)))
    empty_sse = np.full(64, np.inf)
    gmin, gmax = POLICY['GAIN_MIN'], POLICY['GAIN_MAX']
    for dy in range(2 * SHIFT + 1):
        for dx in range(2 * SHIFT + 1):
            O = tiles[:, dy:dy + WIN, dx:dx + WIN].reshape(64, -1, 3)
            Oc = (O - O.mean(axis=1, keepdims=True)).reshape(64, -1)
            oo = np.einsum('sn,sn->s', Oc, Oc)
            orr = np.einsum('sn,skn->sk', Oc, Rc)
            g = np.clip(orr / np.maximum(rr, 1e-9), gmin, gmax)
            sse = oo[:, None] - 2 * g * orr + g * g * rr
            better = sse < best
            best = np.where(better, sse, best)
            best_gain = np.where(better, g, best_gain)
            if dx == SHIFT and dy == SHIFT:
                empty_sse = oo                                      # flat square: only the variance is left
    n = WIN * WIN * 3
    scale = cal['contrast'] ** 2
    labels = list(kinds) + ['empty']
    out = {}
    for i, s in enumerate(SQUARES):
        cost = np.concatenate([best[i], [empty_sse[i]]]) / n
        order = np.argsort(cost)
        c1, c2 = cost[order[0]], cost[order[1]] if len(order) > 1 else np.inf
        margin = float(c2 / max(c1, 1e-6))
        fit = float(c1 / scale)
        label = labels[order[0]]
        rec = {'best': label, 'second': labels[order[1]] if len(order) > 1 else None,
               'margin': round(margin, 3) if np.isfinite(margin) else None,
               'fit': round(fit, 4) if np.isfinite(fit) else None,
               'gain': round(float(best_gain[i, order[0]]), 3) if order[0] < len(kinds) else None}
        if not inside[i]:
            rec.update(label='unsure', reason='outside-image')
        elif not np.isfinite(c1):
            rec.update(label='unsure', reason='no-candidate')
        elif fit > POLICY['FIT_MAX']:
            rec.update(label='unsure', reason='poor-fit')
        elif margin < POLICY['MARGIN_MIN']:
            rec.update(label='unsure', reason='small-margin')
        elif label == 'empty':
            rec.update(label='unsure', reason='no-piece-seen')   # occupancy is the square reader's call, not ours
        elif order[0] < len(kinds) and not (gmin < best_gain[i, order[0]] < gmax):
            rec.update(label='unsure', reason='gain-at-limit')
        else:
            rec.update(label=label, reason='ok')
        out[s] = rec
    return out


def read(image, corners, cal):
    tiles, inside = _square_tiles(image, corners)
    return read_tiles(tiles, inside, cal)


def policy():
    return {'TILE': TILE, 'SHIFT': SHIFT, 'SUPERSAMPLE_MAX': SUPERSAMPLE_MAX, **POLICY}


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
    """Pairs of same-colour, different-type pieces standing on squares of the same colour (so the two square
    pictures can be exchanged pixel for pixel): (a, b)."""
    occ = sorted(pos)
    pairs = [(a, b) for i, a in enumerate(occ) for b in occ[i + 1:]
             if pos[a] != pos[b] and pos[a].isupper() == pos[b].isupper() and is_dark(a) == is_dark(b)]
    if len(pairs) > limit:
        pairs = [pairs[j] for j in sorted(rng.choice(len(pairs), limit, replace=False))]
    return pairs


def _verdict(readings, claim):
    """Does the reader contradict the claimed position on the changed squares? noticed / missed / unsure."""
    if any(r not in ('unsure', claim[s]) for s, r in readings.items()):
        return 'noticed'
    if all(r == claim[s] for s, r in readings.items()):
        return 'missed'
    return 'unsure'


def evaluate(scenes, split, out, swaps_per_picture=3, limit_games=None, dump_squares=False):
    if 'held' in split:
        raise SystemExit('held-out splits are off limits for this prototype')
    scenes = Path(scenes)
    games = [g for g in json.loads((scenes / 'truth/games.json').read_text())['games'] if g['split'] == split]
    if limit_games:
        games = games[:limit_games]
    rng = np.random.default_rng(12345)
    rows, swap_rows, timing, starts = [], [], [], []
    for game in games:
        n_start = _start_count(game)
        frames = game['frames']
        start = [(np.asarray(Image.open(scenes / f['file']).convert('RGB'), np.float32), f['corners'])
                 for f in frames[:n_start]]
        try:
            cal = calibrate(start, game['startFen'])
        except CalibrationError as e:
            starts.append({'game': game['id'], 'ok': False, 'reason': str(e)})
            continue
        starts.append({'game': game['id'], 'ok': True, 'kinds': ''.join(cal['kinds'])})
        for f in frames[n_start:]:
            if f.get('transition'):
                continue
            img = np.asarray(Image.open(scenes / f['file']).convert('RGB'), np.float32)
            t0 = time.perf_counter()
            tiles, inside = _square_tiles(img, f['corners'])
            t1 = time.perf_counter()
            res = read_tiles(tiles, inside, cal)
            t2 = time.perf_counter()
            timing.append(((t1 - t0) * 1000, (t2 - t1) * 1000))
            truth = placement(f['fen'])
            cond, blur = _condition(game, f), _blur_bucket(f)
            for s in SQUARES:
                rec = res[s]
                row = {'g': game['id'], 'i': f['index'], 's': s, 't': truth.get(s, 'empty'), 'r': rec['label'],
                       'cond': cond, 'blur': blur}
                if dump_squares:
                    row.update(best=rec['best'], second=rec['second'], margin=rec['margin'], fit=rec['fit'],
                               gain=rec['gain'], reason=rec['reason'])
                rows.append(row)
            # constructed swaps and substitutions in the rectified board (claim = the true position)
            for a, b in _swap_cases(truth, rng, swaps_per_picture):
                ia, ib = SQUARES.index(a), SQUARES.index(b)
                sw = tiles.copy()
                sw[ia], sw[ib] = tiles[ib], tiles[ia]
                r_sw = read_tiles(sw, inside, cal)
                sub = tiles.copy()
                sub[ib] = tiles[ia]                               # b now shows a's piece
                r_sub = read_tiles(sub, inside, cal)
                swap_rows.append({'g': game['id'], 'i': f['index'], 'a': a, 'b': b, 'pa': truth[a], 'pb': truth[b],
                                  'cond': cond,
                                  'swap': _verdict({a: r_sw[a]['label'], b: r_sw[b]['label']}, truth),
                                  'swapReads': [r_sw[a]['label'], r_sw[b]['label']],
                                  'sub': _verdict({b: r_sub[b]['label']}, truth),
                                  'subRead': r_sub[b]['label'],
                                  'baseline': _verdict({a: res[a]['label'], b: res[b]['label']}, truth)})
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    doc = {'schema': 'piece-classifier-v1-eval', 'split': split, 'note': 'simulated images only; true corners',
           'policy': policy(), 'starts': starts, 'timingMs': timing, 'squares': rows, 'swaps': swap_rows}
    (out / f'{split}.json').write_text(json.dumps(doc))
    print(summarise(doc))
    return doc


def _count(rows, key=None):
    """Occupied squares only: correct / wrong-type / wrong-empty / unsure."""
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
    lines = [f"split {doc['split']}: starts accepted {sum(s['ok'] for s in doc['starts'])} of {len(doc['starts'])}"]
    for name, key in (('all', None), ('type', lambda r: r['t'].upper() + ('w' if r['t'].isupper() else 'b')),
                      ('condition', lambda r: r['cond']), ('blur', lambda r: r['blur'])):
        for k, c in sorted(_count(rows, key).items()):
            lines.append(f"  {name:9s} {k:20s} correct {c['correct']} of {c['n']}, wrong {c['wrongType'] + c['wrongEmpty']}"
                         f" (type {c['wrongType']}, empty {c['wrongEmpty']}), unsure {c['unsure']}")
    empties = [r for r in rows if r['t'] == 'empty']
    lines.append(f"  empty squares named as a piece: {sum(r['r'] in PIECES for r in empties)} of {len(empties)}")
    sw = doc['swaps']
    for kind in ('swap', 'sub', 'baseline'):
        tally = {v: sum(1 for x in sw if x[kind] == v) for v in ('noticed', 'missed', 'unsure')}
        lines.append(f"  {kind:8s} noticed {tally['noticed']} / missed {tally['missed']} / unsure {tally['unsure']}"
                     f" of {len(sw)}")
    if doc['timingMs']:
        t = np.asarray(doc['timingMs'])
        lines.append(f"  ms per picture: rectify median {np.median(t[:, 0]):.0f}, read median {np.median(t[:, 1]):.0f},"
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
