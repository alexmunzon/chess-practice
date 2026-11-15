#!/usr/bin/env python3
"""Offline "board on a screen" recognition pipeline (experiment, not app code; simulated images only).

Joins three prototypes without changing them:
  1. corners   native/ScreenBoardVision binary (corners clockwise from the one nearest image top-left)
  2. squares   scripts/recognition/occupancy_classifier.py (calibrate / classify on a 640x640 panel)
  3. move      src/core/occupancy-move-inference.js via scripts/recognition/occupancy-infer-cli.mjs

Per game: the start frame (simulated review of startFen) is rectified once in screen-upright order
(pieces stand as drawn) and calibrated against startFen's occupancy turned to each of the 4
orientations; it is accepted only if EXACTLY ONE calibrates, which fixes the board orientation. Each later frame: detect corners, pick the rotation whose corners
lie nearest the last accepted frame's (abstain if none is clearly nearest or it differs from the locked one), rectify, classify,
reorder a8..h1 -> a1..h8, inferMove against the tracked FEN. "unchanged" keeps the FEN; a "move"
advances it only when AGREE_FRAMES consecutive usable pictures each infer the SAME move from the
SAME tracked FEN (agreement guard); everything else withholds. Several start pictures: calibrate on
the first that passes the 4-rotation test; every later usable start picture must read "unchanged".
Truth is used for startFen only.

CLI: python3 -B scripts/recognition/screen_pipeline.py --scenes ROOT --game ID --out DIR [--classifier v2|v3] [--agree N]
"""
import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/recognition'))
import occupancy_classifier as oc  # noqa: E402

BUILD = Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15/pipeline')
DEFAULT_DETECTOR = BUILD / 'bin/screen-board-detect'
INFER_CLI = ROOT / 'scripts/recognition/occupancy-infer-cli.mjs'
PANEL = 640
BOARD_LO, BOARD_HI = oc.BOARD_ORIGIN[0], oc.BOARD_ORIGIN[0] + 8 * oc.TILE_SIZE  # 64..576

# ---- Pipeline policy (set on smoke/dev and single-position dev scenes only; written into every output). ----
POLICY = {
    'ROTATION_MAX_SHIFT_FRAC': 0.25,   # best rotation's mean corner shift vs reference, as a share of board side
    'ROTATION_MIN_MARGIN': 2.0,        # second-best mean shift / best mean shift must be at least this
    'SUPERSAMPLE_MAX': 3,              # area-average up to 3x3 samples per panel pixel when the board is large
    'ASSUME_UNTOUCHED_UNKNOWNS': False,  # inferMove strict default: any unknown square -> uncertain
    'REFERENCE_UPDATE': 'accepted-frames-only',
    'PANEL_ORIENTATION': 'screen-upright',   # classify the panel as drawn on screen; labels rotated afterwards
    'ROTATION_MUST_MATCH_START': True,       # a frame whose nearest rotation differs from the locked one is withheld
    # Agreement guard (round 2). A move is accepted only when AGREE_FRAMES consecutive usable pictures each infer
    # the same move from the same tracked FEN. A picture in between that reads "unchanged", no-legal, ambiguous or
    # another move RESETS the count; an unusable one (detector, orientation, unknowns) is skipped, at most 2. AGREE_FRAMES=1 = round 1.
    'AGREE_FRAMES': 2,
    'AGREE_INTERRUPTION': 'skip-unusable',  # or 'reset'; skipped = detector/orientation/unknown squares only (set on dev2)
    'AGREE_MAX_SKIPPED': 2,          # with skip-unusable: at most this many unusable pictures in between
    'START_PICTURES': 'calibrate-first-passing-then-others-must-read-unchanged',
}
CLASSIFIERS = {'v2': 'occupancy_classifier', 'v3': 'occupancy_classifier_v3'}
_CLASSIFIER = {'name': 'v2', 'module': oc}


def set_classifier(name):
    """Pick the square classifier (v2 default, v3 lazily imported). Neither file is ever edited here."""
    if name not in CLASSIFIERS:
        raise SystemExit(f'unknown classifier {name!r}; choose v2 or v3')
    try:
        module = importlib.import_module(CLASSIFIERS[name])
    except ModuleNotFoundError as error:
        raise SystemExit(f'classifier {name} needs scripts/recognition/{CLASSIFIERS[name]}.py, which does not exist '
                         f'yet ({error}). Use --classifier v2 or wait for that file.') from error
    for attr in ('calibrate', 'classify', 'CalibrationError'):
        if not hasattr(module, attr):
            raise SystemExit(f'{CLASSIFIERS[name]}.py has no {attr}(); it must match the v2 API')
    _CLASSIFIER.update(name=name, module=module)
    return module


def clf():
    return _CLASSIFIER['module']
SQUARES_A8H1 = oc.SQUARES                                   # classifier order
SQUARES_A1H8 = ['abcdefgh'[i % 8] + str(i // 8 + 1) for i in range(64)]  # inferMove order
SHORT = {'empty': '.', 'white': 'w', 'black': 'b', 'unknown': '?'}
ACCEPTED = ('move', 'unchanged')


def policy():
    mod = clf()
    doc = {'pipeline': dict(POLICY), 'classifier': mod.policy() if hasattr(mod, 'policy') else {}}
    if _CLASSIFIER['name'] != 'v2':  # v2 keeps the round-1 hash layout
        doc['classifierName'] = _CLASSIFIER['name']
    doc['sha256'] = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    return doc


# ------------------------------------------------------------------ square order ----
def a8h1_to_a1h8(values):
    """64 values in a8,b8,...,h8,a7,...,h1 order -> a1,b1,...,h1,a2,...,h8 order."""
    values = list(values)
    if len(values) != 64:
        raise ValueError('need 64 values')
    return [values[(7 - j // 8) * 8 + j % 8] for j in range(64)]


def screen_from_a8(values, r):
    """64 values in a8..h1 order -> tile order of the screen-upright panel, when detector corner r is a8.
    The a8-up panel equals the screen panel turned r quarter turns counter-clockwise (np.rot90 k=r)."""
    return np.rot90(np.asarray(values, dtype=object).reshape(8, 8), -r).ravel().tolist()


def a8_from_screen(values, r):
    return np.rot90(np.asarray(values, dtype=object).reshape(8, 8), r).ravel().tolist()


def labels_a8h1(result):
    return [result[s]['label'] for s in SQUARES_A8H1]


def placement(fen):
    return fen.split()[0]


# ------------------------------------------------------------------ geometry ----
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
    xc = np.clip(x, 0, wid - 1.001)
    yc = np.clip(y, 0, hgt - 1.001)
    x0 = np.floor(xc).astype(np.int32)
    y0 = np.floor(yc).astype(np.int32)
    fx = (xc - x0)[..., None]
    fy = (yc - y0)[..., None]
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy)
            + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)


def board_side(corners):
    c = np.asarray(corners, float)
    return float(np.mean([np.linalg.norm(c[k] - c[(k + 1) % 4]) for k in range(4)]))


def rectify(image, corners):
    """Warp the quad `corners` (a8, h8, h1, a1 outer playing-area corners, image coords with pixel
    centres at integers) onto panel pixels 64..576. Area-averages k x k sub-samples per panel pixel
    when the board is larger than 512 px in the image (avoids aliasing). Outside is filled grey."""
    img = image if isinstance(image, np.ndarray) else np.asarray(image.convert('RGB'), np.float32)
    corners = np.asarray(corners, float)
    h = homography([(BOARD_LO, BOARD_LO), (BOARD_HI, BOARD_LO), (BOARD_HI, BOARD_HI), (BOARD_LO, BOARD_HI)],
                   corners)
    k = int(min(POLICY['SUPERSAMPLE_MAX'], max(1, math.ceil(board_side(corners) / (BOARD_HI - BOARD_LO) - 0.05))))
    n = BOARD_HI - BOARD_LO
    acc = np.zeros((n, n, 3), np.float32)
    base = np.arange(n, dtype=np.float64) + BOARD_LO
    for oy in (np.arange(k) + 0.5) / k:
        for ox in (np.arange(k) + 0.5) / k:
            u, v = np.meshgrid(base + ox, base + oy)  # panel continuous coords (pixel edges at integers)
            den = h[2, 0] * u + h[2, 1] * v + h[2, 2]
            x = (h[0, 0] * u + h[0, 1] * v + h[0, 2]) / den
            y = (h[1, 0] * u + h[1, 1] * v + h[1, 2]) / den
            acc += _bilinear(img, x, y)
    panel = np.full((PANEL, PANEL, 3), 128, np.uint8)
    panel[BOARD_LO:BOARD_HI, BOARD_LO:BOARD_HI] = np.clip(acc / (k * k) + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(panel, 'RGB')


def rotate(corners, r):
    """Rotation r: corner r of the detector's clockwise list becomes a8; result is a8, h8, h1, a1."""
    corners = [list(map(float, c)) for c in corners]
    return corners[r:] + corners[:r]


def choose_rotation(detected, reference):
    """Pick the rotation of `detected` nearest `reference` (a8,h8,h1,a1). Returns (r, info) or (None, info)."""
    ref = np.asarray(reference, float)
    shifts = [float(np.mean(np.linalg.norm(np.asarray(rotate(detected, r)) - ref, axis=1))) for r in range(4)]
    order = np.argsort(shifts)
    best, second = shifts[order[0]], shifts[order[1]]
    side = board_side(reference)
    info = {'meanShiftPx': round(best, 2), 'shiftFrac': round(best / side, 4),
            'margin': round(second / max(best, 1.0), 2), 'shiftsPx': [round(s, 1) for s in shifts]}
    if best > POLICY['ROTATION_MAX_SHIFT_FRAC'] * side or second < POLICY['ROTATION_MIN_MARGIN'] * max(best, 1.0):
        return None, info
    return int(order[0]), info


def order_like_detector(corners):
    """Any 4 board corners in cyclic order -> clockwise (y down) from the one nearest image top-left."""
    c = np.asarray(corners, float)
    centre = c.mean(0)
    ang = np.arctan2(c[:, 1] - centre[1], c[:, 0] - centre[0])
    c = c[np.argsort(ang)]  # increasing angle with y down = clockwise on screen
    start = int(np.argmin(np.linalg.norm(c, axis=1)))
    return np.roll(c, -start, axis=0).tolist()


# ------------------------------------------------------------------ detector ----
def run_detector(paths, binary=DEFAULT_DETECTOR, chunk=40):
    """Run the corner binary on image paths (stateless per image; batched to save process starts)."""
    out = {}
    paths = [str(p) for p in paths]
    for i in range(0, len(paths), chunk):
        part = paths[i:i + chunk]
        proc = subprocess.run([str(binary), *part], capture_output=True, text=True, check=False)
        for line in proc.stdout.splitlines():
            if line.strip():
                d = json.loads(line)
                out[d['image']] = d
        for p in part:
            out.setdefault(p, {'found': False, 'reason': f'detector-exit-{proc.returncode}', 'confidence': 0})
    return out


# ------------------------------------------------------------------ inference bridge ----
class InferBridge:
    """One long-lived node process answering inferMove requests over JSON lines."""

    def __init__(self):
        self.proc = subprocess.Popen(['node', str(INFER_CLI)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, bufsize=1, cwd=str(ROOT))
        self.n = 0

    def infer(self, fen, occupancy_a1h8, options=None):
        self.n += 1
        req = {'id': self.n, 'fen': fen, 'occupancy': list(occupancy_a1h8), 'options': options or {}}
        self.proc.stdin.write(json.dumps(req) + '\n')
        self.proc.stdin.flush()
        reply = json.loads(self.proc.stdout.readline())
        if reply.get('id') != self.n:
            raise RuntimeError(f'bridge out of sync: {reply}')
        if 'error' in reply:
            raise RuntimeError(reply['error'])
        return reply['result']

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ------------------------------------------------------------------ tracker ----
def load_image(path):
    t = time.perf_counter()
    arr = np.asarray(Image.open(path).convert('RGB'), np.float32)
    return arr, (time.perf_counter() - t) * 1000


def _det_summary(det):
    return {'found': bool(det.get('found')), 'confidence': det.get('confidence', 0), 'reason': det.get('reason'),
            'ms': round(float(det.get('decodeMs', 0)) + float(det.get('detectMs', 0)), 1),
            'corners': det.get('corners')}


class GameTracker:
    """Tracks one game from frames. `classify_cache` (optional dict) lets an evaluator reuse
    (frame, rotation) classifications across scoring modes; results are identical either way."""

    def __init__(self, start_fen, bridge, classify_cache=None):
        self.start_fen = start_fen
        self.bridge = bridge
        self.cache = classify_cache if classify_cache is not None else {}
        self.fen = None
        self.calibration = None
        self.rotation = None
        self.reference = None
        self.started = False
        self.start_closed = False  # a later start picture contradicted the start: no further attempts
        self.pending = None        # agreement guard: {'uci', 'fen', 'fenAfter', 'recs'}

    def start(self, index, image, det, decode_ms=0.0):
        """One start picture. Before the start is locked it tries the 4-rotation test; afterwards each
        further start picture must read "unchanged" (a contradiction rejects the whole start)."""
        if self.started:
            return self._confirm_start(index, image, det, decode_ms)
        rec = {'index': index, 'stage': 'start', 'detector': _det_summary(det), 'timingsMs': {'decode': round(decode_ms, 1)}}
        rec['timingsMs']['detect'] = rec['detector']['ms']
        if self.start_closed:
            rec.update(status='start-rejected', cause='start-picture-disagreed-earlier', trackedFen=None)
            return rec
        if not det.get('found'):
            rec.update(status='start-rejected', cause='detector', trackedFen=None)
            return rec
        if callable(image):
            image = image()
        ok, tried = [], []
        t = time.perf_counter()
        panel = rectify(image, det['corners'])  # screen-upright panel: pieces stand as drawn on screen
        a8_grid = [oc.occupancy_from_fen(self.start_fen)[s] for s in SQUARES_A8H1]
        for r in range(4):
            stated = dict(zip(SQUARES_A8H1, screen_from_a8(a8_grid, r)))  # tile names = panel positions
            try:
                cal = clf().calibrate(panel, stated)
                ok.append((r, cal, rotate(det['corners'], r)))
                tried.append({'rotation': r, 'calibrated': True})
            except clf().CalibrationError as error:
                tried.append({'rotation': r, 'calibrated': False, 'error': str(error)[:160]})
        rec['timingsMs']['startCalibration'] = round((time.perf_counter() - t) * 1000, 1)
        rec['rotationsTried'] = tried
        if len(ok) != 1:
            rec.update(status='start-rejected', cause=f'{len(ok)}-rotations-calibrated', trackedFen=None)
            return rec
        self.rotation, self.calibration, self.reference = ok[0]
        self.fen = self.start_fen
        self.started = True
        rec.update(status='start-accepted', rotation=self.rotation, trackedFen=self.fen,
                   startLabel='simulated review')
        return rec

    def _confirm_start(self, index, image, det, decode_ms):
        rec = self.step(index, image, det, decode_ms)
        rec['stage'] = 'start-confirm'
        inferred = (rec.get('inference') or {}).get('status')
        if rec['status'] == 'accepted' and inferred == 'unchanged':
            rec['startCheck'] = 'agrees'
        elif inferred in ('move', 'ambiguous', 'no-legal-explanation'):
            rec['startCheck'] = 'contradicts'  # the start pictures disagree: reject the whole start
            self._drop_pending()
            self.started, self.fen, self.start_closed = False, None, True
            rec.update(status='start-rejected', cause='start-picture-disagrees', trackedFen=None)
        else:
            rec['startCheck'] = 'unusable'  # detector / orientation / unknown squares: neither for nor against
        return rec
    def classify_frame(self, key, image, screen_corners, r):
        """Classify the screen-upright panel (detector corner order), then turn labels into a8..h1 order."""
        if key not in self.cache:
            self.cache[key] = self._classify_screen(image, screen_corners)
        out = dict(self.cache[key])
        out['labels'] = a8_from_screen(out['screenLabels'], r)
        return out

    def _classify_screen(self, image, corners):
        if callable(image):  # lazy loader: decode only on a cache miss
            image = image()
        t = time.perf_counter()
        panel = rectify(image, corners)
        t1 = time.perf_counter()
        result = clf().classify(panel, self.calibration)
        t2 = time.perf_counter()
        labels = labels_a8h1(result)  # tile order of the screen-upright panel
        reasons = {}
        for s in SQUARES_A8H1:
            for r in result[s]['reasons']:
                reasons[r] = reasons.get(r, 0) + 1
        return {'screenLabels': labels, 'reasons': reasons, 'rectifyMs': (t1 - t) * 1000,
                'classifyMs': (t2 - t1) * 1000}

    def step(self, index, image, det, decode_ms=0.0, cache_key=None):
        rec = {'index': index, 'stage': 'frame', 'detector': _det_summary(det), 'trackedFenBefore': self.fen,
               'timingsMs': {'decode': round(decode_ms, 1)}}
        rec['timingsMs']['detect'] = rec['detector']['ms']
        if not self.started:
            rec.update(status='withheld', cause='no-start', trackedFen=self.fen)
            return rec
        if not det.get('found'):
            self._unusable_picture()
            rec.update(status='withheld', cause='detector', trackedFen=self.fen)
            return rec
        r, info = choose_rotation(det['corners'], self.reference)
        rec['rotationCheck'] = info
        if r is None:
            self._unusable_picture()
            rec.update(status='withheld', cause='orientation', trackedFen=self.fen)
            return rec
        rec['rotation'] = r
        if r != self.rotation:  # the screen turned relative to the locked start orientation
            self._unusable_picture()
            rec.update(status='withheld', cause='orientation', trackedFen=self.fen)
            return rec
        corners = rotate(det['corners'], r)
        cl = self.classify_frame(cache_key if cache_key is not None else index, image, det['corners'], r)
        rec['timingsMs'].update(rectify=round(cl['rectifyMs'], 1), classify=round(cl['classifyMs'], 1))
        rec['labelsA8H1'] = ''.join(SHORT[x] for x in cl['labels'])
        rec['unknownReasons'] = cl['reasons']
        t = time.perf_counter()
        res = self.bridge.infer(self.fen, a8h1_to_a1h8(cl['labels']),
                                {'assumeUntouchedUnknowns': True} if POLICY['ASSUME_UNTOUCHED_UNKNOWNS'] else {})
        rec['timingsMs']['infer'] = round((time.perf_counter() - t) * 1000, 2)
        rec['inference'] = {k: v for k, v in res.items() if k in ('status', 'cause', 'unknownSquares')}
        if res['status'] == 'ambiguous':
            rec['inference']['candidates'] = [c['uci'] for c in res['candidates']]
        if res['status'] == 'move':
            uci = res['move']['uci']
            rec.update(inferredMove=uci, inferredFen=res['fenAfter'])
            p = self.pending
            if p is not None and p['uci'] == uci and p['fen'] == self.fen:
                p['recs'].append(rec)
            else:
                self._drop_pending()
                p = self.pending = {'uci': uci, 'fen': self.fen, 'fenAfter': res['fenAfter'], 'recs': [rec]}
            rec['agreeCount'] = len(p['recs'])
            if len(p['recs']) >= POLICY['AGREE_FRAMES']:
                for earlier in p['recs']:
                    earlier['guard'] = 'confirmed'
                self.pending = None
                rec['acceptedMove'] = uci
                self.fen = p['fenAfter']
                self.reference = corners
                rec.update(status='accepted')
            else:
                rec['guard'] = 'waiting'
                rec.update(status='pending', cause='awaiting-agreement')
        elif res['status'] == 'unchanged':
            self._drop_pending()
            self.reference = corners
            rec.update(status='accepted')
        else:
            if res['status'] == 'uncertain':  # unknown squares: the picture says nothing either way
                self._unusable_picture()
            else:  # no-legal-explanation / ambiguous: the picture disagrees with the pending move
                self._drop_pending()
            rec.update(status='withheld', cause={'uncertain': 'classifier-unknowns', 'ambiguous': 'ambiguous-promotion'
                                                 if res.get('cause') == 'promotion-piece-choice' else 'ambiguous-other',
                                                 'no-legal-explanation': 'no-legal-explanation'}[res['status']])
        rec['trackedFen'] = self.fen
        return rec

    def _unusable_picture(self):
        """Detector miss, orientation refusal or unknown squares while a move waits for agreement.
        'reset' drops the pending move; 'skip-unusable' keeps it for at most AGREE_MAX_SKIPPED such
        pictures. Skipping is safe: confirmation still needs another picture inferring the SAME move
        from the SAME tracked FEN, and a picture of any other position reads another move,
        unchanged or no-legal-explanation, all of which reset."""
        p = self.pending
        if p is None:
            return
        if POLICY['AGREE_INTERRUPTION'] == 'skip-unusable' and p.get('skipped', 0) < POLICY['AGREE_MAX_SKIPPED']:
            p['skipped'] = p.get('skipped', 0) + 1
        else:
            self._drop_pending()

    def _drop_pending(self, outcome='discarded'):
        if self.pending is not None:
            for rec in self.pending['recs']:
                rec['guard'] = outcome
            self.pending = None

    def finish(self):
        """End of the picture stream: a move still waiting for agreement was never accepted."""
        self._drop_pending('unresolved')

    def human_rereview(self, fen, corners=None):
        """Simulated human re-review: the human confirms the position (and the board's corners if visible)."""
        self._drop_pending()
        self.fen = fen
        if corners is not None:
            self.reference = corners


def position_of(frame):
    """Position number of a picture: `positionIndex` in multi-picture roots, else the frame index."""
    return frame.get('positionIndex', frame['index'])


def is_start_picture(frame):
    return position_of(frame) == 0


def load_games(scenes):
    return json.loads((Path(scenes) / 'truth/games.json').read_text())


def run_game(scenes, game, out=None, binary=DEFAULT_DETECTOR):
    """Strict single pass (no re-review). Uses truth only for game['startFen']."""
    scenes = Path(scenes)
    paths = [scenes / f['file'] for f in game['frames']]
    dets = run_detector(paths, binary)
    trace = []
    with InferBridge() as bridge:
        tracker = GameTracker(game['startFen'], bridge)
        for f, p in zip(game['frames'], paths):
            img, dms = load_image(p)
            det = dets[str(p)]
            rec = (tracker.start(f['index'], img, det, dms) if is_start_picture(f)
                   else tracker.step(f['index'], img, det, dms))
            rec['file'] = f['file']
            trace.append(rec)
        tracker.finish()
    doc = {'schema': 'screen-pipeline-trace-v1', 'game': game['id'], 'policy': policy(),
           'note': 'simulated images only; start frame = simulated review of startFen', 'frames': trace}
    if out:
        out = Path(out); out.mkdir(parents=True, exist_ok=True)
        (out / f"{game['id']}.trace.json").write_text(json.dumps(doc, indent=1))
    return doc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--scenes', required=True, type=Path)
    ap.add_argument('--game', required=True)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--detector', type=Path, default=DEFAULT_DETECTOR)
    ap.add_argument('--classifier', default='v2', choices=sorted(CLASSIFIERS))
    ap.add_argument('--agree', type=int, default=POLICY['AGREE_FRAMES'])
    a = ap.parse_args()
    set_classifier(a.classifier)
    POLICY['AGREE_FRAMES'] = a.agree
    games = {g['id']: g for g in load_games(a.scenes)['games']}
    doc = run_game(a.scenes, games[a.game], a.out, a.detector)
    counts = {}
    for r in doc['frames']:
        key = r['status'] + ('/' + r['cause'] if r.get('cause') else '')
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({'game': a.game, 'frames': len(doc['frames']), 'statuses': counts,
                      'finalFen': doc['frames'][-1]['trackedFen'], 'trace': str(a.out / f"{a.game}.trace.json")}))


if __name__ == '__main__':
    main()
