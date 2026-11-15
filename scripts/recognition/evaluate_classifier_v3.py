#!/usr/bin/env python3
"""Harness for the v3 square reader (Worker J; experiment, simulated images only).

Scores occupancy_classifier (v2, frozen) and occupancy_classifier_v3 side by side on
DEVELOPMENT data only. Held-out splits are refused by name; this script never lists them.

  prepare  run the corner detector once and cache rectified screen-upright panels
           (true corners and detected corners) for game frames and single-position scenes
  games    start acceptance per game + per-square scoring of every later frame
  single   per-square scoring of the single-position scenes (cross-scene calibration)
  sweep    robustness sweep on rectified dev panels
  all      games + single (+ sweep with --sweep)

Rectification is a verbatim copy of screen_pipeline.rectify (2026-11-15) so Worker B's edits to
that file cannot change these numbers; the detector binary is the pipeline's own.
"""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/recognition'))
import occupancy_classifier as v2  # noqa: E402
import occupancy_classifier_v3 as v3  # noqa: E402

GAMES_ROOTS = {'scenes': Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15/scenes'),
               'scenes-v2': Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15/scenes-v2')}
GAME_SPLITS = {'scenes': ('smoke', 'dev'), 'scenes-v2': ('smoke2', 'dev2')}
SINGLE_ROOT = Path('/Users/alexmunzon/chess-builds/screen-board-2026-11-15')
SINGLE_SPLIT = 'dev'
DETECTOR = Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15/pipeline/bin/screen-board-detect')
OUT = Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15/classifier-v3')
FORBIDDEN = ('heldout',)  # any split whose name contains this is never read
PANEL, LO, HI = 640, 64, 576
SQ = v2.SQUARES  # a8..h1
CLASSIFIERS = {'v2': v2, 'v3': v3}


def _allowed(split):
    if any(f in split for f in FORBIDDEN):
        raise SystemExit(f'refusing forbidden split {split!r}')
    return split


# ------------------------------------------------------------ geometry (copy) ----
def homography(src, dst):
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.asarray(rows, float))
    h = vt[-1].reshape(3, 3)
    return h / h[2, 2]


def _bilinear(img, x, y):
    hgt, wid = img.shape[:2]
    xc = np.clip(x, 0, wid - 1.001); yc = np.clip(y, 0, hgt - 1.001)
    x0 = np.floor(xc).astype(np.int32); y0 = np.floor(yc).astype(np.int32)
    fx = (xc - x0)[..., None]; fy = (yc - y0)[..., None]
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy)
            + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)


def board_side(c):
    c = np.asarray(c, float)
    return float(np.mean([np.linalg.norm(c[k] - c[(k + 1) % 4]) for k in range(4)]))


def rectify(img, corners):
    corners = np.asarray(corners, float)
    h = homography([(LO, LO), (HI, LO), (HI, HI), (LO, HI)], corners)
    k = int(min(3, max(1, math.ceil(board_side(corners) / (HI - LO) - 0.05))))
    n = HI - LO
    acc = np.zeros((n, n, 3), np.float32)
    base = np.arange(n, dtype=np.float64) + LO
    for oy in (np.arange(k) + 0.5) / k:
        for ox in (np.arange(k) + 0.5) / k:
            u, v = np.meshgrid(base + ox, base + oy)
            den = h[2, 0] * u + h[2, 1] * v + h[2, 2]
            acc += _bilinear(img, (h[0, 0] * u + h[0, 1] * v + h[0, 2]) / den,
                             (h[1, 0] * u + h[1, 1] * v + h[1, 2]) / den)
    panel = np.full((PANEL, PANEL, 3), 128, np.uint8)
    panel[LO:HI, LO:HI] = np.clip(acc / (k * k) + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(panel, 'RGB')


def rotate(corners, r):
    corners = [list(map(float, c)) for c in corners]
    return corners[r:] + corners[:r]


def nearest_rotation(detected, reference):
    ref = np.asarray(reference, float)
    shifts = [float(np.mean(np.linalg.norm(np.asarray(rotate(detected, r)) - ref, axis=1))) for r in range(4)]
    return int(np.argmin(shifts)), min(shifts)


def order_like_detector(corners):
    c = np.asarray(corners, float)
    centre = c.mean(0)
    c = c[np.argsort(np.arctan2(c[:, 1] - centre[1], c[:, 0] - centre[0]))]
    start = int(np.argmin(np.linalg.norm(c, axis=1)))
    return np.roll(c, -start, axis=0).tolist()


def screen_from_a8(values, r):
    return np.rot90(np.asarray(values, dtype=object).reshape(8, 8), -r).ravel().tolist()


def a8_from_screen(values, r):
    return np.rot90(np.asarray(values, dtype=object).reshape(8, 8), r).ravel().tolist()


def occ_a8h1(fen):
    o = v2.occupancy_from_fen(fen)
    return [o[s] for s in SQ]


def run_detector(paths, chunk=40):
    out = {}
    paths = [str(p) for p in paths]
    for i in range(0, len(paths), chunk):
        part = paths[i:i + chunk]
        proc = subprocess.run(['nice', '-n', '10', str(DETECTOR), *part], capture_output=True, text=True)
        for line in proc.stdout.splitlines():
            if line.strip():
                d = json.loads(line); out[d['image']] = d
        for p in part:
            out.setdefault(p, {'found': False})
    return out


# ------------------------------------------------------------ dataset index ----
def dataset_items():
    """Yield dicts describing every development picture: kind game|single, ids, file, truth fen, corners."""
    items = []
    for root_name, root in GAMES_ROOTS.items():
        tf = root / 'truth/games.json'
        if not tf.exists():
            continue
        for g in json.loads(tf.read_text())['games']:
            if g['split'] not in GAME_SPLITS[root_name]:
                continue  # held-out games are skipped without opening any image
            _allowed(g['split'])
            for f in g['frames']:
                if not (root / f['file']).exists():
                    continue  # scenes still being generated
                items.append({'kind': 'game', 'root': root_name, 'split': g['split'], 'game': g['id'],
                              'difficulty': g['difficulty'], 'index': f['index'], 'frameKind': f['kind'],
                              'file': str(root / f['file']), 'fen': f['fen'], 'corners': f['corners'],
                              'disturbance': [k for k, v in f['disturbance'].items() if v] or ['none'],
                              'key': f"{root_name}/{g['id']}/{f['index']:03d}"})
    truth = json.loads((SINGLE_ROOT / 'truth/truth.json').read_text())
    boards = {b['file']: b['placement'] for b in truth['boards']}
    for s in truth['scenes']:
        if s['split'] != SINGLE_SPLIT or not s.get('corners'):
            continue
        items.append({'kind': 'single', 'root': 'single', 'split': 'dev', 'game': None, 'difficulty': s['difficulty'],
                      'index': None, 'file': str(SINGLE_ROOT / s['file']), 'fen': boards[s['board']] + ' w - - 0 1',
                      'corners': s['corners'], 'key': f"single/{s['id']}",
                      'disturbance': [k for k in ('glare', 'hand', 'banding') if s.get(k)] or ['none']})
    return items


def panel_path(key, variant):
    return OUT / 'panels' / f"{key.replace('/', '__')}.{variant}.png"


def prepare():
    items = dataset_items()
    detf = OUT / 'detections.json'
    dets = json.loads(detf.read_text()) if detf.exists() else {}
    todo = [it['file'] for it in items if it['file'] not in dets]
    if todo:
        print(f'detector on {len(todo)} images', flush=True)
        dets.update(run_detector(todo))
        OUT.mkdir(parents=True, exist_ok=True)
        detf.write_text(json.dumps(dets))
    meta = {}
    (OUT / 'panels').mkdir(parents=True, exist_ok=True)
    n = 0
    for it in items:
        screen_true = order_like_detector(it['corners'])
        r_true, _ = nearest_rotation(screen_true, it['corners'])
        m = {'rTrue': r_true}
        det = dets.get(it['file'], {})
        if det.get('found'):
            r_det, shift = nearest_rotation(det['corners'], it['corners'])
            m.update(rDet=r_det, cornerErrPx=round(shift, 2))
        meta[it['key']] = m
        need = [('true', screen_true)] + ([('det', det['corners'])] if det.get('found') else [])
        need = [(v, c) for v, c in need if not panel_path(it['key'], v).exists()]
        if need:
            img = np.asarray(Image.open(it['file']).convert('RGB'), np.float32)
            for v, c in need:
                rectify(img, c).save(panel_path(it['key'], v), compress_level=1)
            n += 1
            if n % 50 == 0:
                print(f'  rectified {n}', flush=True)
    (OUT / 'panel-meta.json').write_text(json.dumps(meta))
    print(f'prepared {len(items)} pictures')


def load_panel(key, variant):
    p = panel_path(key, variant)
    return Image.open(p).convert('RGB') if p.exists() else None


# ------------------------------------------------------------ scoring ----
VARIANTS = ('true', 'det')


def try_start(mod, panel, start_fen):
    """4-rotation start check exactly as the pipeline does it. Returns (accepted r or None, cal, list, errors)."""
    a8 = occ_a8h1(start_fen)
    ok, errs = [], {}
    for r in range(4):
        try:
            ok.append((r, mod.calibrate(panel, dict(zip(SQ, screen_from_a8(a8, r))))))
        except mod.CalibrationError as e:
            errs[r] = str(e)[:200]
    if len(ok) == 1:
        return ok[0][0], ok[0][1], [r for r, _ in ok], errs
    return None, None, [r for r, _ in ok], errs


def score_labels(labels_a8, fen):
    truth = occ_a8h1(fen)
    c = sum(a == b for a, b in zip(labels_a8, truth))
    wrong = [f'{s}:{b}->{a}' for s, a, b in zip(SQ, labels_a8, truth) if a not in (b, 'unknown')]
    return {'correct': c, 'wrong': len(wrong), 'unknown': labels_a8.count('unknown'), 'wrongSquares': wrong}


def _bucket():
    return {'frames': 0, 'squares': 0, 'correct': 0, 'wrong': 0, 'unknown': 0, 'all64': 0}


def _add(b, s):
    b['frames'] += 1; b['squares'] += 64
    for k in ('correct', 'wrong', 'unknown'):
        b[k] += s[k]
    b['all64'] += s['correct'] == 64


def classify_panel(mod, panel, cal, r):
    res = mod.classify(panel, cal)
    labels = a8_from_screen([res[s]['label'] for s in SQ], r)
    reasons = {}
    for s in SQ:
        for x in res[s]['reasons']:
            reasons[x] = reasons.get(x, 0) + 1
    return labels, reasons


def eval_games(names, items, meta):
    games = {}
    for it in items:
        if it['kind'] == 'game':
            games.setdefault(it['game'], []).append(it)
    report = {'starts': {}, 'agg': {}, 'frames': []}
    for name in names:
        mod = CLASSIFIERS[name]
        for gid, frames in games.items():
            frames.sort(key=lambda f: f['index'])
            f0 = frames[0]
            for var in VARIANTS:
                panel = load_panel(f0['key'], var)
                rec = {'game': gid, 'split': f0['split'], 'difficulty': f0['difficulty'], 'variant': var}
                if panel is None:
                    rec.update(accepted=False, cause='detector')
                    report['starts'].setdefault(name, []).append(rec)
                    continue
                r_ok = meta[f0['key']]['rTrue' if var == 'true' else 'rDet']
                r, cal, okl, errs = try_start(mod, panel, f0['fen'])
                rec.update(accepted=r is not None, rotationsCalibrated=okl, correctRotation=r_ok,
                           acceptedCorrect=r == r_ok, errors={k: v[:120] for k, v in errs.items()})
                report['starts'].setdefault(name, []).append(rec)
                if r is None:
                    continue
                for f in frames[1:]:
                    p = load_panel(f['key'], var)
                    if p is None:
                        continue
                    rr = meta[f['key']]['rTrue' if var == 'true' else 'rDet']
                    labels, reasons = classify_panel(mod, p, cal, rr)
                    s = score_labels(labels, f['fen'])
                    for key in ('all', f"split={f['split']}", f"difficulty={f['difficulty']}",
                                *(f'dist={d}' for d in f['disturbance']),
                                f"undisturbed-{f['difficulty']}" if f['disturbance'] == ['none'] else None):
                        if key:
                            _add(report['agg'].setdefault(f'{name}|{var}|{key}', _bucket()), s)
                    report['frames'].append({'clf': name, 'variant': var, 'key': f['key'], 'difficulty': f['difficulty'],
                                             'disturbance': f['disturbance'], **s, 'reasons': reasons})
    return report


def eval_single(names, items, meta):
    singles = [it for it in items if it['kind'] == 'single']
    starts = [it for it in singles if it['fen'].split()[0] == v2.START_FEN]
    report = {'starts': {}, 'agg': {}, 'frames': [], 'calibration': {}}
    for name in names:
        mod = CLASSIFIERS[name]
        cal = cal_key = None
        for it in starts:  # start acceptance per start scene (detected corners, like the pipeline)
            row = {'id': it['key'], 'difficulty': it['difficulty'], 'disturbance': it['disturbance']}
            for var in VARIANTS:
                panel = load_panel(it['key'], var)
                if panel is None:
                    continue
                r_ok = meta[it['key']]['rTrue' if var == 'true' else 'rDet']
                r, c, okl, _ = try_start(mod, panel, it['fen'])
                row[var] = {'accepted': r is not None, 'rotations': okl, 'correct': r == r_ok}
                if cal is None and var == 'det' and r is not None and r == r_ok:
                    cal, cal_key = c, it['key']
            report['starts'].setdefault(name, []).append(row)
        report['calibration'][name] = cal_key
        # Same calibration scene for both classifiers when possible (v2's first, dev-0000).
        for it in singles:
            if it['key'] == cal_key:
                continue
            for var in VARIANTS:
                p = load_panel(it['key'], var)
                if p is None:
                    continue
                rr = meta[it['key']]['rTrue' if var == 'true' else 'rDet']
                labels, reasons = classify_panel(mod, p, cal, rr)
                s = score_labels(labels, it['fen'])
                for key in ('all', f"difficulty={it['difficulty']}", *(f'dist={d}' for d in it['disturbance']),
                            f"undisturbed-{it['difficulty']}" if it['disturbance'] == ['none'] else None):
                    if key:
                        _add(report['agg'].setdefault(f'{name}|{var}|{key}', _bucket()), s)
                report['frames'].append({'clf': name, 'variant': var, 'key': it['key'], 'difficulty': it['difficulty'],
                                         'disturbance': it['disturbance'], **s, 'reasons': reasons})
    return report


def print_agg(title, report, names):
    print(f'\n## {title}')
    keys = sorted({k.split('|', 2)[2] for k in report['agg']})
    print('| bucket | corners | ' + ' | '.join(f'{n} wrong / unknown / correct' for n in names) + ' |')
    for key in keys:
        for var in VARIANTS:
            cells = []
            for n in names:
                b = report['agg'].get(f'{n}|{var}|{key}')
                cells.append(f"{b['wrong']} / {b['unknown']} / {b['correct']} of {b['squares']}" if b else '-')
            print(f'| {key} | {var} | ' + ' | '.join(cells) + ' |')
    for n in names:
        st = report['starts'].get(n, [])
        if st and 'variant' in st[0]:
            for var in VARIANTS:
                rows = [s for s in st if s['variant'] == var]
                acc = [s for s in rows if s['accepted']]
                bad = [s['game'] for s in acc if not s['acceptedCorrect']]
                print(f'starts {n} {var}: accepted {len(acc)}/{len(rows)} wrong-orientation {bad} '
                      f'rejected {[s["game"] for s in rows if not s["accepted"]]}')
        elif st:
            for var in VARIANTS:
                rows = [s[var] for s in st if var in s]
                print(f'single starts {n} {var}: accepted {sum(r["accepted"] for r in rows)}/{len(rows)}, '
                      f'wrong orientation {sum(r["accepted"] and not r["correct"] for r in rows)}')
    wrong = [f for f in report['frames'] if f['wrong']]
    for f in wrong:
        print('  WRONG', f['clf'], f['variant'], f['key'], f['wrongSquares'])


# ------------------------------------------------------------ sweep ----
def _arr(img):
    return np.asarray(img, float)


def _img(a):
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), 'RGB')


def _banding(img, amp, period, tilt_deg, phase):
    a = _arr(img)
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    t = math.radians(tilt_deg)
    band = 1 + amp * np.sin(2 * np.pi * (yy * math.cos(t) + xx * math.sin(t)) / period + phase)
    return _img(a * band[..., None])


def _spot(img, cx, cy, amp, sigma):
    a = _arr(img)
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    g = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
    return _img(a + amp * g[..., None])


def _glare(img, radius, seed):  # same blob as v2's sweep
    rng = np.random.default_rng(seed)
    cx, cy = rng.uniform(180, 590), rng.uniform(180, 590)
    a = _arr(img)
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    alpha = np.clip(1.4 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * (radius / 2) ** 2)), 0, 1)[..., None]
    return _img(a * (1 - alpha) + 255 * alpha)


def _jpeg(img, q):
    buf = io.BytesIO(); img.save(buf, format='JPEG', quality=q); buf.seek(0)
    return Image.open(buf).convert('RGB')


SWEEP = ([('none', {})]
         + [('brightness', {'k': k}) for k in (0.5, 0.7, 0.85, 1.15, 1.3)]
         + [('gamma', {'g': g}) for g in (0.6, 1.6)]
         + [('blur', {'r': r}) for r in (1, 2, 3, 4, 5)]
         + [('jpeg', {'q': q}) for q in (70, 50, 30)]
         + [('noise', {'sigma': s}) for s in (8, 16, 24, 40)]
         + [('misregister', {'dx': dx, 'dy': dy}) for dx, dy in ((1, 0), (2, 0), (2, 2), (4, 4), (8, 0))]
         + [('glare', {'radius': r}) for r in (40, 90)]
         + [('banding', {'amp': a, 'period': p, 'tilt': t}) for a in (0.05, 0.1, 0.2, 0.3)
            for p in (16, 40, 100) for t in (0, 10)]
         + [('spot', {'amp': a, 'sigma': s}) for a in (40, 90, 150, 220) for s in (8, 16, 28)])


def perturb(img, kind, p, seed, empty_centres):
    rng = np.random.default_rng(seed)
    if kind == 'brightness':
        return _img(_arr(img) * p['k'])
    if kind == 'gamma':
        return _img(255 * (_arr(img) / 255) ** p['g'])
    if kind == 'blur':
        return img.filter(ImageFilter.GaussianBlur(p['r']))
    if kind == 'jpeg':
        return _jpeg(img, p['q'])
    if kind == 'noise':
        return _img(_arr(img) + rng.normal(0, p['sigma'], _arr(img).shape))
    if kind == 'misregister':
        return _img(np.roll(_arr(img), shift=(p['dy'], p['dx']), axis=(0, 1)))
    if kind == 'glare':
        return _glare(img, p['radius'], seed)
    if kind == 'banding':
        return _banding(img, p['amp'], p['period'], p['tilt'], rng.uniform(0, 6.28))
    if kind == 'spot':  # local bright spot centred on (or near) an empty square
        cx, cy = empty_centres[int(rng.integers(len(empty_centres)))]
        return _spot(img, cx + rng.uniform(-10, 10), cy + rng.uniform(-10, 10), p['amp'], p['sigma'])
    return img


def sweep_plan(items, meta, per_game=6, max_frames=36):
    """Undisturbed dev game frames (true-corner panels) from games whose start v2 AND v3 both accept."""
    games = {}
    for it in items:
        if it['kind'] == 'game' and it['split'] == 'dev':  # old dev games (fixed set, independent of dev2 generation)
            games.setdefault(it['game'], []).append(it)
    plan = []
    for gid, frames in sorted(games.items()):
        frames.sort(key=lambda f: f['index'])
        start = load_panel(frames[0]['key'], 'true')
        if start is None:
            continue
        cals = {}
        for name, mod in CLASSIFIERS.items():
            r, cal, _, _ = try_start(mod, start, frames[0]['fen'])
            if r is None or r != meta[frames[0]['key']]['rTrue']:
                break
            cals[name] = cal
        if len(cals) != 2:
            continue
        clean = [f for f in frames[1:] if f['disturbance'] == ['none']]
        step = max(1, len(clean) // per_game)
        plan.extend((cals, f) for f in clean[::step][:per_game])
    return plan[:max_frames]


def run_sweep(names, items, meta):
    plan = sweep_plan(items, meta)
    print(f'sweep: {len(plan)} undisturbed dev frames (true-corner panels), games '
          f'{sorted({f["game"] for _, f in plan})}', flush=True)
    rows = []
    for kind, params in SWEEP:
        row = {'kind': kind, 'params': params}
        for name in names:
            b = _bucket(); wrong = []
            for n, (cals, f) in enumerate(plan):
                r = meta[f['key']]['rTrue']
                truth_screen = screen_from_a8(occ_a8h1(f['fen']), r)
                centres = [(LO + 32 + 64 * (i % 8), LO + 32 + 64 * (i // 8)) for i in range(64)
                           if truth_screen[i] == 'empty']
                p = perturb(load_panel(f['key'], 'true'), kind, params, 1000 + n, centres)
                labels, _ = classify_panel(CLASSIFIERS[name], p, cals[name], r)
                s = score_labels(labels, f['fen']); _add(b, s)
                wrong.extend(f"{f['key']}:{w}" for w in s['wrongSquares'])
            row[name] = {**b, 'unknownRate': round(b['unknown'] / b['squares'], 4), 'wrongExamples': wrong[:8]}
        rows.append(row)
        print(f"{kind:11s} {json.dumps(params):42s} " + '  '.join(
            f"{n}: wrong {row[n]['wrong']:4d} unk {100 * row[n]['unknownRate']:5.1f}%" for n in names), flush=True)
    (OUT / 'sweep.json').write_text(json.dumps({'frames': [f['key'] for _, f in plan], 'rows': rows}, indent=1))


# ------------------------------------------------------------ original marker corpus ----
CORPUS = Path('/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/'
              'simulation-2026-11-11/corpus')


def eval_corpus(names, splits=('dev', 'challenge')):
    """v2's own corpus evaluation logic (occupancy_classifier.evaluate), run per classifier. Dev and challenge only."""
    pixels, truth = v2._load_corpus(CORPUS)
    sessions = v2._session_plan(truth)
    out = {}
    for name in names:
        mod = CLASSIFIERS[name]
        dev_first = sessions['dev-opening'][0]
        base = mod.calibrate(mod.rectify(pixels / dev_first['file']), mod.occupancy_from_fen(dev_first['fen']))
        tallies, wrong = {}, []
        for sid, frames in sessions.items():
            split = _allowed(frames[0]['split']) if frames[0]['split'] in splits else None
            if split is None:
                continue
            first = frames[0]
            cal, scored = base, frames
            if first['fen'].split()[0] == v2.START_FEN:
                try:
                    cal = mod.calibrate(mod.rectify(pixels / first['file']), mod.occupancy_from_fen(first['fen']))
                    scored = frames[1:]
                except (mod.CalibrationError, ValueError):
                    if sid == 'dev-opening':
                        scored = frames[1:]
            for f in scored:
                result, _ = mod.classify_image(pixels / f['file'], cal)
                sc = v2.score(result, f)
                for key in (f'{split}|all', f'{split}|{v2.category(f)}'):
                    v2._add(tallies.setdefault(key, v2._empty_tally()), sc)
                wrong.extend(f"{f['id']}:{w['square']}:{w['truth']}->{w['got']}" for w in sc['wrongSquares'])
        out[name] = {'tallies': tallies, 'wrong': wrong}
        for k in sorted(tallies):
            t = tallies[k]
            print(f"corpus {name} {k:26s} frames {t['frames']:3d} squares {t['squares']:5d} correct {t['correct']:5d} "
                  f"wrong {t['wrong']:3d} abstained {t['abstained']:4d} all64 {t['framesAll64Correct']}")
    (OUT / 'corpus.json').write_text(json.dumps(out, indent=1))
    return out


# ------------------------------------------------------------ summary ----
def summarise(names=('v2', 'v3')):
    """v2 vs v3 per split and corner source: all scored frames, and the COMMON frames both could score."""
    rep = json.loads((OUT / f"games-{'-'.join(names)}.json").read_text())
    rows = {}
    for f in rep['frames']:
        split = f['key'].split('/')[1].rsplit('-', 1)[0]
        rows.setdefault((f['clf'], f['variant']), {})[f['key']] = (split, f)
    lines = ['| split | corners | frames | ' + ' | '.join(f'{n} wrong / unknown / correct' for n in names)
             + ' | common frames | ' + ' | '.join(f'{n} common w / u / c' for n in names) + ' |']
    undist = ['| split | corners | difficulty | common undisturbed squares | '
              + ' | '.join(f'{n} unknown %' for n in names) + ' |']
    for split in ('smoke', 'dev', 'smoke2', 'dev2'):
        for var in VARIANTS:
            sets = {n: {k: f for k, (sp, f) in rows.get((n, var), {}).items() if sp == split} for n in names}
            common = set.intersection(*(set(v) for v in sets.values()))
            cells, ccells = [], []
            for n in names:
                fs = list(sets[n].values()); cs = [sets[n][k] for k in common]
                cells.append('{} / {} / {} ({})'.format(*(sum(f[x] for f in fs) for x in ('wrong', 'unknown', 'correct')),
                                                        len(fs)))
                ccells.append('{} / {} / {}'.format(*(sum(f[x] for f in cs) for x in ('wrong', 'unknown', 'correct'))))
            lines.append(f'| {split} | {var} | ' + ' | '.join(cells) + f' | {len(common)} | ' + ' | '.join(ccells) + ' |')
            for diff in ('easy', 'medium', 'hard'):
                keys = [k for k in common if sets[names[0]][k]['difficulty'] == diff
                        and sets[names[0]][k]['disturbance'] == ['none']]
                if keys:
                    undist.append(f'| {split} | {var} | {diff} | {64 * len(keys)} | ' + ' | '.join(
                        f"{100 * sum(sets[n][k]['unknown'] for k in keys) / (64 * len(keys)):.1f}" for n in names) + ' |')
    print('\n'.join(lines)); print(); print('\n'.join(undist))
    starts = rep['starts']
    for n in names:
        for var in VARIANTS:
            for split in ('smoke', 'dev', 'smoke2', 'dev2'):
                st = [x for x in starts.get(n, []) if x['variant'] == var and x['split'] == split]
                if st:
                    acc = [x for x in st if x['accepted']]
                    print(f"starts {n} {var} {split}: accepted {len(acc)}/{len(st)}, wrong orientation "
                          f"{sum(not x['acceptedCorrect'] for x in acc)}, rejected {[x['game'] for x in st if not x['accepted']]}")


# ------------------------------------------------------------ main ----
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['prepare', 'games', 'single', 'sweep', 'corpus', 'summary', 'all'])
    ap.add_argument('--classifiers', default='v2,v3')
    a = ap.parse_args()
    if a.mode == 'prepare':
        prepare()
        return
    names = a.classifiers.split(',')
    items = dataset_items()
    meta = json.loads((OUT / 'panel-meta.json').read_text())
    tag = '-'.join(names)
    if a.mode in ('games', 'all'):
        t = time.time()
        rep = eval_games(names, items, meta)
        (OUT / f'games-{tag}.json').write_text(json.dumps(rep, indent=1))
        print_agg(f'game frames ({time.time() - t:.0f} s)', rep, names)
    if a.mode in ('single', 'all'):
        t = time.time()
        rep = eval_single(names, items, meta)
        (OUT / f'single-{tag}.json').write_text(json.dumps(rep, indent=1))
        print_agg(f'single-position dev scenes, calibration {rep["calibration"]} ({time.time() - t:.0f} s)',
                  rep, names)
    if a.mode == 'sweep':
        run_sweep(names, items, meta)
    if a.mode == 'corpus':
        eval_corpus(names)
    if a.mode in ('summary', 'all'):
        summarise(names)


if __name__ == '__main__':
    main()
