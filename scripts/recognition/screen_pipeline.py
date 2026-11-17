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
     [--start-fallback v4]   (off by default; see START_FALLBACK_CLASSIFIER)
     [--start-self-check]    (off by default; see START_SELF_CHECK)
     [--corner-finder original|round2]   (default round2; see FINDERS)
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
# Corner finder by name (same style as the reader choice). 'original' is the frozen finder (sha256 b5774046...);
# 'round2' is the reviewed round-2 finder (sha256 3292bcae...; strict improvement on ordinary pictures, NOT a guard
# against lens distortion). The reviewed round2 finder is now the default; original remains selectable.
FINDERS = {'original': DEFAULT_DETECTOR, 'round2': BUILD / 'bin/screen-board-detect-round2'}
DEFAULT_FINDER = 'round2'
_FINDER = {'name': DEFAULT_FINDER}
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
    'AGREE_MODE': 'consecutive',     # or 'window': AGREE_FRAMES of any AGREE_WINDOW pictures (measured, not adopted)
    'AGREE_WINDOW': 3,
    # "Position confirmed current" (round 3): `unchanged` keeps the FEN from one picture, but a picture reports
    # currentConfirmed only if it is the picture that confirmed a move by agreement, a reviewed start picture,
    # or the latest of CURRENT_CONFIRM_FRAMES consecutive `unchanged` readings counted AFTER the last accepted
    # move / human review (unusable pictures neither count nor break the run; no-legal/ambiguous/move break it).
    # A moved position misread as unchanged therefore needs that many consecutive misreads to look confirmed.
    # Downstream advice is fresh only while currentConfirmed is true.
    'CURRENT_CONFIRM_FRAMES': 'AGREE_FRAMES',
    # Self-aware review request (round 3): the pipeline asks a human when SELF_REVIEW_AFTER_WITHHELD pictures in a row
    # were withheld (pending pictures neither count nor break the run), or on SELF_REVIEW_AFTER_NO_LEGAL
    # no-legal-explanation readings in a row. Set on dev/dev2.
    'SELF_REVIEW_AFTER_WITHHELD': 3,
    'SELF_REVIEW_AFTER_NO_LEGAL': 1,
    # The caller says which pictures belong to the human-reviewed start (start_pictures); the pipeline
    # calibrates on the first that passes the 4-rotation test, the others must read "unchanged".
    'START_PICTURES': 'caller-supplied-count; calibrate-first-passing-then-others-must-read-unchanged',
}
CLASSIFIERS = {'v2': 'occupancy_classifier', 'v3': 'occupancy_classifier_v3', 'v4': 'occupancy_classifier_v4'}
_CLASSIFIER = {'name': None, 'module': None}  # filled by set_classifier(DEFAULT_CLASSIFIER) below
DEFAULT_CLASSIFIER = 'v3'  # CLI and library default; v2 (blur-gate hole closed only in v3.1) only when asked by name
# Start fallback ("backup reader at game start"). None = off (default; behaviour identical to before the option).
# 'v4' = when the current reader calibrates the start picture in NONE of the 4 orientations, try this reader on
# the same picture; if it calibrates exactly one AND its own reading of that picture is exactly the stated start
# (self-check: 64 of 64 squares, no unknown), the start is accepted and THIS reader reads the rest of that game
# (its calibration is the game's calibration). Never used when the current reader accepts, or when it refuses because
# 2+ orientations calibrated (an ambiguous orientation is a protective refusal). Keep None until the v4.3 review
# approves v4.3. Set with set_start_fallback(name) or --start-fallback; see docs/SCREEN_PIPELINE.md.
START_FALLBACK_CLASSIFIER = None
# Start self-check for the default reader. False = off (default; behaviour identical to before the option). True = when
# the default reader calibrates exactly one orientation of the start picture, read that same picture back with the new
# calibration and accept the start only if all 64 squares come back exactly as stated (the fallback's self-check, now
# also on the default reader's starts). A start refused this way is never handed to the fallback. Set with
# set_start_self_check(on) or --start-self-check; see docs/SCREEN_PIPELINE.md.
START_SELF_CHECK = False


def _import_classifier(name):
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
    return module


def set_classifier(name):
    """Pick the square classifier by name (module imported on demand). Neither file is ever edited here."""
    module = _import_classifier(name)
    _CLASSIFIER.update(name=name, module=module)
    return module


def set_start_fallback(name):
    """Turn the start fallback on (a reader name from CLASSIFIERS) or off (None). Returns the previous setting so a
    caller can restore it. Trackers read the setting when they are created; a running game is not affected."""
    global START_FALLBACK_CLASSIFIER
    if name is not None:
        _import_classifier(name)  # fail now, not at the first refused start
    old, START_FALLBACK_CLASSIFIER = START_FALLBACK_CLASSIFIER, name
    return old


def set_start_self_check(on):
    """Turn the default reader's start self-check on (True) or off (False). Returns the previous setting so a caller
    can restore it. Trackers read the setting when they are created; a running game is not affected."""
    global START_SELF_CHECK
    old, START_SELF_CHECK = START_SELF_CHECK, bool(on)
    return old


set_classifier(DEFAULT_CLASSIFIER)  # start-up reader is v3, so callers that never pick one get the safe reader


def set_finder(name):
    """Pick the corner finder by name. Refuses an unknown name or a binary that is missing or not executable
    (SystemExit; the current finder stays). Returns the previous name so a caller can restore it. Never falls back to
    another finder: if the chosen binary disappears later, run_detector records detector errors for every picture."""
    if name not in FINDERS:
        raise SystemExit(f'unknown corner finder {name!r}; choose one of {", ".join(sorted(FINDERS))}')
    path = Path(FINDERS[name])
    if not (path.is_file() and os.access(path, os.X_OK)):
        raise SystemExit(f'corner finder {name} needs {path}, which is missing or not executable')
    old = _FINDER['name']
    _FINDER['name'] = name
    return old


def finder_path():
    """Binary of the selected corner finder (no existence check here: a missing binary becomes detector errors)."""
    return FINDERS[_FINDER['name']]


def clf():
    return _CLASSIFIER['module']


SQUARES_A8H1 = oc.SQUARES                                   # classifier order
SQUARES_A1H8 = ['abcdefgh'[i % 8] + str(i // 8 + 1) for i in range(64)]  # inferMove order
SHORT = {'empty': '.', 'white': 'w', 'black': 'b', 'unknown': '?'}
ACCEPTED = ('move', 'unchanged')


def policy(binary=None):
    mod = clf()
    doc = {'pipeline': dict(POLICY), 'classifier': mod.policy() if hasattr(mod, 'policy') else {}}
    if _CLASSIFIER['name'] != 'v2':  # v2 keeps the round-1 hash layout
        doc['classifierName'] = _CLASSIFIER['name']
    if START_FALLBACK_CLASSIFIER is not None:  # only when on, so the policy hash with the fallback off is unchanged
        fb = _import_classifier(START_FALLBACK_CLASSIFIER)
        doc['startFallback'] = {'classifierName': START_FALLBACK_CLASSIFIER,
                                'classifier': fb.policy() if hasattr(fb, 'policy') else {},
                                'rule': 'tried only when the reader calibrates 0 of 4 orientations of a start picture; '
                                        'accepted only if it calibrates exactly 1 and reads that picture back as the '
                                        'stated start on all 64 squares; the reader that accepted the start reads '
                                        'the rest of the game'}
    if START_SELF_CHECK:  # only when on, so the policy hash with the option off is unchanged
        doc['startSelfCheck'] = {'rule': 'a start the default reader calibrates in exactly 1 orientation is accepted '
                                         'only if that reader then reads the start picture back as the stated start '
                                         'on all 64 squares; a refused start is not handed to the fallback'}
    detector = Path(binary) if binary is not None else Path(finder_path())
    name = next((name for name, path in FINDERS.items() if Path(path) == detector), 'custom')
    if name != 'original':  # preserve original-era hashes; identify the actual binary for other runs
        doc['cornerFinder'] = {'name': name, 'binarySha256': _file_sha256(detector)}
        if name == 'custom':
            doc['cornerFinder']['binaryPath'] = str(detector)
    doc['sha256'] = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    return doc


def _file_sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None  # missing binary: recorded as such; the run itself then fails closed with detector errors


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
def run_detector(paths, binary=None, chunk=40):
    """Run the corner binary on image paths (stateless per image; batched to save process starts).
    binary=None = the selected corner finder (set_finder; default 'round2').
    A crash, a non-zero exit, malformed JSON or a missing answer is recorded as a DETECTOR ERROR
    (`error: true`, reason detector-error:...), never as "board not found"; a warning is printed."""
    if binary is None:
        binary = finder_path()
    out = {}
    paths = [str(p) for p in paths]
    for i in range(0, len(paths), chunk):
        part = paths[i:i + chunk]
        try:
            proc = subprocess.run([str(binary), *part], capture_output=True, text=True, check=False)
            stdout, code = proc.stdout, proc.returncode
        except OSError as error:
            stdout, code = '', f'oserror:{error.__class__.__name__}'
        got = {}
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                got[d['image']] = d
            except (ValueError, KeyError, TypeError):
                code = code or 'malformed-output'
        for p in part:
            d = got.get(p)
            if d is None or code != 0 or d.get('reason') == 'unreadable-image' or \
                    (d.get('found') and not (isinstance(d.get('corners'), list) and len(d['corners']) == 4)):
                why = 'unreadable-image' if d is not None and d.get('reason') == 'unreadable-image' else \
                    ('missing-answer' if d is None else 'malformed-answer')
                d = {'image': p, 'found': False, 'error': True, 'confidence': 0,
                     'reason': f'detector-error:{why}:exit={code}'}
                print(f'WARNING detector error on {p}: {d["reason"]}', file=sys.stderr)
            out[p] = d
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
    return {'found': bool(det.get('found')), 'error': bool(det.get('error')), 'confidence': det.get('confidence', 0),
            'reason': det.get('reason'),
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
        self.pending = None        # agreement guard: {'uci', 'fen', 'fenAfter', 'recs', 'skipped', 'span'}
        self.unchanged_run = 0     # consecutive "unchanged" readings (for currentConfirmed)
        self.withheld_run = 0      # consecutive withheld pictures (for the self-aware review request)
        self.no_legal_run = 0
        self.start_fallback = START_FALLBACK_CLASSIFIER  # read once: one game never changes its fallback setting
        self.reader_name = None    # fallback on: name of the reader that accepted the start (reads the whole game)
        self.reader_module = None  # set only when the fallback reader accepted the start; None = clf()
        self.start_self_check = START_SELF_CHECK  # read once, like the fallback setting

    def _calibrate_rotations(self, module, panel, a8_grid, corners):
        ok, tried = [], []
        for r in range(4):
            stated = dict(zip(SQUARES_A8H1, screen_from_a8(a8_grid, r)))  # tile names = panel positions
            try:
                cal = module.calibrate(panel, stated)
                ok.append((r, cal, rotate(corners, r)))
                tried.append({'rotation': r, 'calibrated': True})
            except module.CalibrationError as error:
                tried.append({'rotation': r, 'calibrated': False, 'error': str(error)[:160]})
        return ok, tried

    @staticmethod
    def _fallback_self_check(module, panel, a8_grid, accepted, rec):
        """Fallback path only. A reader's start check (calibrate) does not apply the rules it uses on later pictures,
        so v4.3 alone accepts some pictures that are not the start (independent review, 2026-11-16). Read the start
        picture itself with the new calibration: accept only if all 64 squares come back exactly as stated
        (no unknown, no other label). Records the result in rec['fallbackSelfCheck']; returns True if it passes."""
        off = GameTracker._read_back(module, panel, a8_grid, accepted)
        rec['fallbackSelfCheck'] = {'passed': not off, 'squaresNotAsStated': len(off), 'examples': dict(list(off.items())[:4])}
        if off:
            rec['startFallback'] = 'refused-self-check'
        return not off

    @staticmethod
    def _read_back(module, panel, a8_grid, accepted):
        """Read the start picture with the calibration it just produced; returns {square: 'stated->read'} for every
        square that does not come back exactly as stated (empty dict = all 64 as stated)."""
        r, cal, _ = accepted
        result = module.classify(panel, cal)
        read = a8_from_screen(labels_a8h1(result), r)  # screen-upright tiles -> a8..h1 board squares
        return {s: f'{want}->{got}' for s, want, got in zip(SQUARES_A8H1, a8_grid, read) if got != want}

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
            rec.update(status='start-rejected', cause='detector-error' if det.get('error') else 'detector-not-found',
                       trackedFen=None)
            return rec
        if callable(image):
            image = image()
        t = time.perf_counter()
        panel = rectify(image, det['corners'])  # screen-upright panel: pieces stand as drawn on screen
        a8_grid = [oc.occupancy_from_fen(self.start_fen)[s] for s in SQUARES_A8H1]
        ok, tried = self._calibrate_rotations(clf(), panel, a8_grid, det['corners'])
        cause = f'{len(ok)}-rotations-calibrated'  # the default reader's verdict names a refusal
        via_fallback = False
        self_check_refused = False
        if self.start_self_check and len(ok) == 1:
            t_check = time.perf_counter()
            off = self._read_back(clf(), panel, a8_grid, ok[0])
            rec['startSelfCheck'] = {'passed': not off, 'squaresNotAsStated': len(off),
                                     'examples': dict(list(off.items())[:4]),
                                     'ms': round((time.perf_counter() - t_check) * 1000, 1)}
            if off:  # the reader calibrated, but its own reading of this picture is not the stated start: refuse
                ok, cause, self_check_refused = [], 'start-self-check-failed', True
        if self.start_fallback is not None:
            if self_check_refused:
                rec['startFallback'] = 'not-tried'   # a protective refusal, like an ambiguous orientation
            elif len(ok) == 1:
                rec['startFallback'] = 'not-needed'  # the default reader accepted: the fallback is never asked
            elif ok or self.start_fallback == _CLASSIFIER['name']:
                rec['startFallback'] = 'not-tried'   # 2+ orientations fit: ambiguous, a refusal that protects
            else:
                fb = _import_classifier(self.start_fallback)
                ok, rec['fallbackRotationsTried'] = self._calibrate_rotations(fb, panel, a8_grid, det['corners'])
                if len(ok) == 1 and not self._fallback_self_check(fb, panel, a8_grid, ok[0], rec):
                    ok = []  # the backup's own reading of its start picture is not the stated start: refuse
                via_fallback = len(ok) == 1
                rec['startFallback'] = 'accepted' if via_fallback else rec.get('startFallback', 'refused')
        rec['timingsMs']['startCalibration'] = round((time.perf_counter() - t) * 1000, 1)
        rec['rotationsTried'] = tried
        if len(ok) != 1:
            rec.update(status='start-rejected', cause=cause, trackedFen=None)
            return rec
        if self.start_fallback is not None:
            self.reader_name = self.start_fallback if via_fallback else _CLASSIFIER['name']
            self.reader_module = fb if via_fallback else None
            rec['startReader'] = self.reader_name
        self.rotation, self.calibration, self.reference = ok[0]
        self.fen = self.start_fen
        self.started = True
        self.unchanged_run = 0  # the reviewed start picture itself is current (currentConfirmed below)
        rec.update(status='start-accepted', rotation=self.rotation, trackedFen=self.fen, currentConfirmed=True,
                   startLabel='simulated review')
        return rec

    def _confirm_start(self, index, image, det, decode_ms):
        rec = self._step(index, image, det, decode_ms)  # no review-request bookkeeping inside the start review
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
        rec['currentConfirmed'] = rec['status'] == 'accepted'
        return rec

    def classify_frame(self, key, image, screen_corners, r):
        """Classify the screen-upright panel (detector corner order), then turn labels into a8..h1 order."""
        if self.reader_module is not None:  # fallback reader: its readings never share a cache slot with the default's
            key = (self.reader_name, key)
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
        result = (self.reader_module or clf()).classify(panel, self.calibration)  # the reader that calibrated
        t2 = time.perf_counter()
        labels = labels_a8h1(result)  # tile order of the screen-upright panel
        reasons = {}
        for s in SQUARES_A8H1:
            for r in result[s]['reasons']:
                reasons[r] = reasons.get(r, 0) + 1
        return {'screenLabels': labels, 'reasons': reasons, 'rectifyMs': (t1 - t) * 1000,
                'classifyMs': (t2 - t1) * 1000}

    @staticmethod
    def _confirm_frames():
        n = POLICY['CURRENT_CONFIRM_FRAMES']
        return POLICY['AGREE_FRAMES'] if n == 'AGREE_FRAMES' else int(n)

    def step(self, index, image, det, decode_ms=0.0, cache_key=None):
        rec = self._step(index, image, det, decode_ms, cache_key)
        if rec['status'] != 'pending':  # pending pictures neither count nor break the withheld run
            self.withheld_run = self.withheld_run + 1 if rec['status'] == 'withheld' else 0
        nl = (rec.get('inference') or {}).get('status') == 'no-legal-explanation'
        self.no_legal_run = self.no_legal_run + 1 if nl else 0
        rec['currentConfirmed'] = bool(rec['status'] == 'accepted' and (
            rec.get('acceptedMove') or self.unchanged_run >= self._confirm_frames()))
        if self.started and rec['stage'] != 'start-confirm' and (
                self.withheld_run >= POLICY['SELF_REVIEW_AFTER_WITHHELD']
                or self.no_legal_run >= POLICY['SELF_REVIEW_AFTER_NO_LEGAL']):
            rec['reviewRequested'] = 'no-legal-explanation' if nl and \
                self.no_legal_run >= POLICY['SELF_REVIEW_AFTER_NO_LEGAL'] else f'{self.withheld_run}-withheld-in-a-row'
        return rec

    def _step(self, index, image, det, decode_ms=0.0, cache_key=None):
        rec = {'index': index, 'stage': 'frame', 'detector': _det_summary(det), 'trackedFenBefore': self.fen,
               'timingsMs': {'decode': round(decode_ms, 1)}}
        rec['timingsMs']['detect'] = rec['detector']['ms']
        if not self.started:
            rec.update(status='withheld', cause='no-start', trackedFen=self.fen)
            return rec
        if not det.get('found'):
            self._unusable_picture()
            rec.update(status='withheld', cause='detector-error' if det.get('error') else 'detector-not-found',
                       trackedFen=self.fen)
            return rec
        r, info = choose_rotation(det['corners'], self.reference)
        rec['rotationCheck'] = info
        rec['rotation'] = r
        if r is None or r != self.rotation:  # no clear rotation, or the screen turned vs the locked start
            self._unusable_picture()
            rec.update(status='withheld', cause='orientation', trackedFen=self.fen)
            return rec
        corners = rotate(det['corners'], r)
        cl = self.classify_frame(cache_key if cache_key is not None else index, image, det['corners'], r)
        rec['timingsMs'].update(rectify=round(cl['rectifyMs'], 1), classify=round(cl['classifyMs'], 1))
        rec['labelsA8H1'] = ''.join(SHORT[x] for x in cl['labels'])
        rec['unknownReasons'] = cl['reasons']
        if self.start_fallback is not None:
            rec['reader'] = self.reader_name
        t = time.perf_counter()
        res = self.bridge.infer(self.fen, a8h1_to_a1h8(cl['labels']),
                                {'assumeUntouchedUnknowns': True} if POLICY['ASSUME_UNTOUCHED_UNKNOWNS'] else {})
        rec['timingsMs']['infer'] = round((time.perf_counter() - t) * 1000, 2)
        rec['inference'] = {k: v for k, v in res.items() if k in ('status', 'cause', 'unknownSquares')}
        if res['status'] == 'ambiguous':
            rec['inference']['candidates'] = [c['uci'] for c in res['candidates']]
        window = POLICY['AGREE_MODE'] == 'window'
        if self.pending is not None:
            self.pending['span'] += 1  # pictures seen since the pending move's first reading (window mode)
            if window and self.pending['span'] > POLICY['AGREE_WINDOW']:
                self._drop_pending()
        if res['status'] == 'move':
            uci = res['move']['uci']
            rec.update(inferredMove=uci, inferredFen=res['fenAfter'])
            self.unchanged_run = 0
            p = self.pending
            if p is not None and p['uci'] == uci and p['fen'] == self.fen:
                p['recs'].append(rec)
            else:
                self._drop_pending()
                p = self.pending = {'uci': uci, 'fen': self.fen, 'fenAfter': res['fenAfter'], 'recs': [rec],
                                    'skipped': 0, 'span': 1}
            rec['agreeCount'] = len(p['recs'])
            if len(p['recs']) >= POLICY['AGREE_FRAMES']:
                for earlier in p['recs']:
                    earlier['guard'] = 'confirmed'
                self.pending = None
                rec['acceptedMove'] = uci
                self.fen = p['fenAfter']
                self.reference = corners
                self.unchanged_run = 0  # this picture is confirmed current (agreement); later unchanged runs restart
                rec.update(status='accepted')
            else:
                rec['guard'] = 'waiting'
                rec.update(status='pending', cause='awaiting-agreement')
        elif res['status'] == 'unchanged':
            self._drop_pending()
            self.unchanged_run += 1
            self.reference = corners
            rec.update(status='accepted')
        else:
            if res['status'] == 'uncertain' or (window and res['status'] in ('no-legal-explanation', 'ambiguous')):
                self._unusable_picture()  # says nothing either way (window mode: misreads are not conflicts)
            else:  # no-legal-explanation / ambiguous: the picture disagrees with the pending move
                self._drop_pending()
                self.unchanged_run = 0
            rec.update(status='withheld', cause={'uncertain': 'classifier-unknowns', 'ambiguous': 'ambiguous-promotion'
                                                 if res.get('cause') == 'promotion-piece-choice' else 'ambiguous-other',
                                                 'no-legal-explanation': 'no-legal-explanation'}[res['status']])
        rec['trackedFen'] = self.fen
        return rec

    def _unusable_picture(self):
        """Detector miss/error, orientation refusal or unknown squares while a move waits for agreement.
        'reset' drops the pending move; 'skip-unusable' keeps it for at most AGREE_MAX_SKIPPED such
        pictures ('window' mode: until AGREE_WINDOW pictures have passed). Skipping is safe: confirmation
        still needs another picture inferring the SAME move from the SAME tracked FEN, and a usable
        picture of any other position reads another move, unchanged or no-legal-explanation."""
        p = self.pending
        if p is None:
            return
        if POLICY['AGREE_MODE'] == 'window':
            return  # bounded by the window span check in _step
        if POLICY['AGREE_INTERRUPTION'] == 'skip-unusable' and p['skipped'] < POLICY['AGREE_MAX_SKIPPED']:
            p['skipped'] += 1
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
        self.unchanged_run = 0
        self.withheld_run = self.no_legal_run = 0
        if corners is not None:
            self.reference = corners


def load_games(scenes):
    return json.loads((Path(scenes) / 'truth/games.json').read_text())


def run_game(scenes, game, out=None, binary=None, start_pictures=1):
    """Strict single pass (no re-review). Uses only game['startFen'], the picture files in order and
    `start_pictures` (how many leading pictures the human reviewed as the start, supplied by the caller)."""
    scenes = Path(scenes)
    paths = [scenes / f['file'] for f in game['frames']]
    dets = run_detector(paths, binary)
    trace = []
    with InferBridge() as bridge:
        tracker = GameTracker(game['startFen'], bridge)
        for n, (f, p) in enumerate(zip(game['frames'], paths)):
            img, dms = load_image(p)
            det = dets[str(p)]
            rec = (tracker.start(f['index'], img, det, dms) if n < start_pictures
                   else tracker.step(f['index'], img, det, dms))
            rec['file'] = f['file']
            trace.append(rec)
        tracker.finish()
    doc = {'schema': 'screen-pipeline-trace-v1', 'game': game['id'], 'policy': policy(binary),
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
    finder_args = ap.add_mutually_exclusive_group()
    finder_args.add_argument('--detector', type=Path, default=None, help='corner binary by path (overrides default finder)')
    finder_args.add_argument('--corner-finder', default=None, choices=sorted(FINDERS),
                    help=f'corner finder by name (default {DEFAULT_FINDER})')
    ap.add_argument('--classifier', default=DEFAULT_CLASSIFIER, choices=sorted(CLASSIFIERS))
    ap.add_argument('--start-pictures', type=int, default=1,
                    help='how many leading pictures the human reviewed as the start position (default 1)')
    ap.add_argument('--agree', type=int, default=POLICY['AGREE_FRAMES'])
    ap.add_argument('--start-fallback', choices=sorted(CLASSIFIERS), default=None,
                    help='backup reader tried only when --classifier refuses a start picture (off by default; '
                         'keep off until the v4.3 review approves v4)')
    ap.add_argument('--start-self-check', action='store_true',
                    help='the default reader must read its start picture back as the stated start (off by default)')
    a = ap.parse_args()
    if a.detector is None:
        set_finder(a.corner_finder or DEFAULT_FINDER)
    set_classifier(a.classifier)
    set_start_fallback(a.start_fallback)
    set_start_self_check(a.start_self_check)
    POLICY['AGREE_FRAMES'] = a.agree
    games = {g['id']: g for g in load_games(a.scenes)['games']}
    doc = run_game(a.scenes, games[a.game], a.out, a.detector, a.start_pictures)
    counts = {}
    for r in doc['frames']:
        key = r['status'] + ('/' + r['cause'] if r.get('cause') else '')
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({'game': a.game, 'frames': len(doc['frames']), 'statuses': counts,
                      'finalFen': doc['frames'][-1]['trackedFen'], 'trace': str(a.out / f"{a.game}.trace.json")}))


if __name__ == '__main__':
    main()
