#!/usr/bin/env python3
"""Three-way square occupancy prototype: EMPTY / WHITE / BLACK (or UNKNOWN).

Experiment only, not app code. The classifier never sees piece templates, piece
types or the simulation recognizer's labels. Everything it knows about colours
comes from ONE human-confirmed starting frame (``calibrate``); every later frame
is judged against those learned references (``classify``). Board location and
rectification reuse the marker geometry in scripts/simulation/recognize.py.

Modes:
  evaluate  --corpus DIR --out DIR [--split dev|heldout|challenge|all]
  sweep     --corpus DIR --out DIR   (perturbations of clean dev frames)
"""
import argparse
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
import recognize as _geometry  # noqa: E402  (geometry only: _markers, _rectify)
from appearance import BOARD_ORIGIN, TILE_SIZE  # noqa: E402

SQUARES = ['abcdefgh'[i % 8] + str(8 - i // 8) for i in range(64)]
DARK = [(i // 8 + i % 8) % 2 for i in range(64)]  # a8 light, a1 dark
LABELS = ('empty', 'white', 'black', 'unknown')

# ---- Fixed policy. Frozen 2026-11-15 before any held-out or challenge frame was scored. ----
PRE_BLUR_RADIUS = 1.0        # Gaussian denoise before pixel tests
FG_DISTANCE = 40.0           # RGB distance from the square's empty reference that counts as "not board"
EMPTY_MAX_FG = 0.03          # foreground fraction at or below which a square is empty
PIECE_MIN_FG = 0.08          # foreground fraction at or above which a square is occupied
BORDER_MAX_FRAC = 0.20       # border-ring pixels allowed to differ from the empty reference
CORE_MIN_DEPTH = 2           # colour is read only >= this many px inside the filled silhouette ...
CORE_DEPTH_BAND = 3          # ... and within this many px of the deepest point
COLOUR_MAX_ROW = 46          # colour is read only above this tile row (piece body, not its base)
MIN_CORE_PIXELS = 6          # core pixels needed to name a colour
COLOR_VOTE_MIN = 0.75        # share of core pixels that must vote for one colour reference
COLOR_MAX_DIST = 70.0        # median core-pixel distance to the nearer reference above this = unfamiliar
SATURATED_LEVEL = 250        # all three raw channels at or above this = clipped / specular
SATURATED_MAX_FRAC = 0.05    # clipped fraction of the square that forces abstention
GAIN_RANGE = (0.5, 2.0)      # per-frame lighting correction allowed relative to calibration
MIN_SAMPLES_PER_CLASS = 2    # squares needed for each of the six references
# Post-freeze addition (v2), after the sweep found blur r=5 wrong-confident squares. Held-out and
# challenge were re-run with it; v1 results are kept beside the v2 ones. Set to 0 to reproduce v1.
FRAME_SHARPNESS_MIN = 0.4    # square-boundary contrast vs calibration frame; below = whole frame unknown
ABSTAIN_BELOW = 0.5          # every component score is scaled so its gate sits at 0.5

# Tile regions (64x64 tile). Pieces in this synthetic style stay inside cols 15-51, rows 5-56.
_BORDER = np.zeros((TILE_SIZE, TILE_SIZE), dtype=bool)
_BORDER[3:7, 3:-3] = True; _BORDER[-7:-3, 3:-3] = True
_BORDER[3:-3, 3:7] = True; _BORDER[3:-3, -7:-3] = True
_WINDOW = np.zeros((TILE_SIZE, TILE_SIZE), dtype=bool)
_WINDOW[8:58, 12:52] = True


class CalibrationError(ValueError):
    """The supposedly confirmed start frame does not match its stated occupancy."""


def policy():
    return {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float, tuple))
            and k not in ('TILE_SIZE',)}


# ---------------------------------------------------------------- geometry ----
def rectify(image):
    """Image (PIL or path) -> 640x640 rectified panel (PIL) using visible markers. Raises ValueError."""
    if not isinstance(image, Image.Image):
        image = Image.open(image)
    image = image.convert('RGB')
    try:
        panel, _ = _geometry._rectify(image, _geometry._markers(image))
    except np.linalg.LinAlgError as error:
        raise ValueError('geometry-unavailable') from error
    return panel


def _prepare(panel):
    if isinstance(panel, np.ndarray):
        panel = Image.fromarray(np.clip(panel, 0, 255).astype(np.uint8), 'RGB')
    raw = np.asarray(panel.convert('RGB'), dtype=float)
    smooth = np.asarray(panel.convert('RGB').filter(ImageFilter.GaussianBlur(PRE_BLUR_RADIUS)), dtype=float)
    return raw, smooth


def _tiles(pixels):
    x, y = BOARD_ORIGIN
    return [pixels[y + r * TILE_SIZE:y + (r + 1) * TILE_SIZE, x + c * TILE_SIZE:x + (c + 1) * TILE_SIZE]
            for r in range(8) for c in range(8)]


def occupancy_from_fen(fen):
    rows, out = fen.split()[0].split('/'), []
    for row in rows:
        for ch in row:
            out.extend(['empty'] * int(ch) if ch.isdigit() else ['white' if ch.isupper() else 'black'])
    if len(out) != 64:
        raise ValueError('bad placement')
    return dict(zip(SQUARES, out))


def _clamp(v):
    return float(min(1.0, max(0.0, v)))


def _measure(tile, empty_ref):
    """Foreground fraction, border mismatch and median foreground colour of one tile."""
    dist = np.linalg.norm(tile - empty_ref, axis=2)
    fg = (dist > FG_DISTANCE) & _WINDOW
    fg_frac = float(fg.sum() / _WINDOW.sum())
    border_frac = float((dist[_BORDER] > FG_DISTANCE).mean())
    colour = None  # core pixels (N x 3) deep inside the piece silhouette
    if fg.sum() >= MIN_CORE_PIXELS:
        weights = _deep_core(fg)
        weights[COLOUR_MAX_ROW:] = 0  # skip the plinth zone (contact shadows / outline-heavy bases)
        core = weights > 0
        if core.sum() >= MIN_CORE_PIXELS:
            colour = (tile[core], weights[core].astype(float))
    return fg_frac, border_frac, colour


def _colour_vote(core, white_ref, black_ref):
    """Each core pixel votes (weighted by depth) for the nearer reference. Returns (label,
    winning vote share, median distance of core pixels to their nearer reference)."""
    core_pixels, weights = core
    d_w = np.linalg.norm(core_pixels - white_ref, axis=1)
    d_b = np.linalg.norm(core_pixels - black_ref, axis=1)
    white_share = float(weights[d_w < d_b].sum() / weights.sum())
    label = 'white' if white_share >= 0.5 else 'black'
    return label, max(white_share, 1 - white_share), float(np.median(np.minimum(d_w, d_b)))


def _fill_holes(mask):
    """Silhouette = mask plus every pixel not reachable from the tile edge without crossing the mask."""
    outside = np.zeros_like(mask)
    outside[0, :] = outside[-1, :] = outside[:, 0] = outside[:, -1] = True
    outside &= ~mask
    for _ in range(TILE_SIZE * 4):
        grown = outside.copy()  # 4-connected growth, so a diagonal gap in an outline does not leak
        grown[1:] |= outside[:-1]; grown[:-1] |= outside[1:]
        grown[:, 1:] |= outside[:, :-1]; grown[:, :-1] |= outside[:, 1:]
        grown &= ~mask
        if (grown == outside).all():
            break
        outside = grown
    return ~outside


def _deep_core(fg):
    """Pixels deepest inside the filled silhouette. Outlines and thin parts (often the opposite
    colour in drawn pieces, and the least reliable pixels on real pieces) are excluded."""
    current = _fill_holes(fg)
    depth = np.zeros(fg.shape, dtype=int)
    for level in range(1, 20):
        current = np.asarray(Image.fromarray(current.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(3))) > 0
        if not current.any():
            break
        depth[current] = level
    floor = max(CORE_MIN_DEPTH, int(depth.max()) - CORE_DEPTH_BAND)
    return np.where(depth >= floor, depth - floor + 1, 0)  # weight: 1 at the band floor, more deeper in


def _sharpness(pixels):
    """Median light/dark contrast across vertical square boundaries (steepest 3-px step), divided by the
    contrast 8 px either side (brightness-invariant; drops when the frame is blurred)."""
    lum = pixels.mean(axis=2)
    x0, y0 = BOARD_ORIGIN
    ratios = []
    for r in range(8):
        rows = slice(y0 + r * TILE_SIZE + 4, y0 + r * TILE_SIZE + 12)  # top strip, above most pieces
        for c in range(1, 8):
            x = x0 + c * TILE_SIZE
            # steepest 3-px step within +-4 px of the nominal boundary, so small misregistration is tolerated
            near = max(abs(lum[rows, x + o - 2].mean() - lum[rows, x + o + 1].mean()) for o in range(-4, 5))
            far = abs(lum[rows, x - 9].mean() - lum[rows, x + 8].mean())
            if far > 10:
                ratios.append(near / far)
    return float(np.median(ratios)) if ratios else 0.0


# ------------------------------------------------------------- calibration ----
def calibrate(start_image_rectified, start_occupancy):
    """Learn six references from one confirmed frame; reject if pixels disagree with the stated occupancy.

    start_occupancy: {square: 'empty'|'white'|'black'} for all 64 squares (e.g. occupancy_from_fen(START)).
    Returns a dict calibration. Raises CalibrationError on any mismatch.
    """
    if set(start_occupancy) != set(SQUARES) or not set(start_occupancy.values()) <= {'empty', 'white', 'black'}:
        raise CalibrationError('occupancy must label all 64 squares empty/white/black')
    _, smooth = _prepare(start_image_rectified)
    tiles = _tiles(smooth)
    occ = [start_occupancy[s] for s in SQUARES]
    empty_ref = []
    for parity in (0, 1):
        idx = [i for i in range(64) if occ[i] == 'empty' and DARK[i] == parity]
        if len(idx) < MIN_SAMPLES_PER_CLASS:
            raise CalibrationError(f'too-few-empty-{"dark" if parity else "light"}-squares')
        empty_ref.append(np.median(np.concatenate([tiles[i][_BORDER | _WINDOW] for i in idx]), axis=0))
    measures = [_measure(tiles[i], empty_ref[DARK[i]]) for i in range(64)]
    problems = []
    piece_ref = {}
    for colour in ('white', 'black'):
        for parity in (0, 1):
            idx = [i for i in range(64) if occ[i] == colour and DARK[i] == parity]
            colours = [measures[i][2] for i in idx if measures[i][2] is not None]
            if len(colours) < MIN_SAMPLES_PER_CLASS:
                raise CalibrationError(f'too-few-{colour}-on-{"dark" if parity else "light"}-squares')
            piece_ref[(colour, parity)] = np.median(np.concatenate([c[0] for c in colours]), axis=0)
    for i, (fg, border, colour) in enumerate(measures):
        if border > BORDER_MAX_FRAC:
            problems.append((SQUARES[i], 'background-mismatch'))
        elif occ[i] == 'empty':
            if fg > EMPTY_MAX_FG:
                problems.append((SQUARES[i], 'stated-empty-but-occupied'))
        elif fg < PIECE_MIN_FG or colour is None:
            problems.append((SQUARES[i], 'stated-occupied-but-empty'))
        else:
            label, share, dist = _colour_vote(colour, piece_ref[('white', DARK[i])], piece_ref[('black', DARK[i])])
            if label != occ[i] or share < COLOR_VOTE_MIN or dist > COLOR_MAX_DIST:
                problems.append((SQUARES[i], f'stated-{occ[i]}-colour-mismatch'))
    for parity in (0, 1):
        w, b = piece_ref[('white', parity)], piece_ref[('black', parity)]
        if w.mean() <= b.mean():
            problems.append(('*', 'white-reference-not-lighter-than-black'))
    if problems:
        raise CalibrationError(f'{len(problems)} square(s) disagree with stated occupancy: '
                               + ', '.join(f'{s}:{r}' for s, r in problems[:8]))
    return {'emptyRef': [r.tolist() for r in empty_ref], 'boundarySharpness': _sharpness(smooth),
            'pieceRef': {f'{c}-{"dark" if p else "light"}': v.tolist() for (c, p), v in piece_ref.items()},
            'policy': policy()}


# ---------------------------------------------------------- classification ----
def _abstain_all(reason):
    return {s: {'label': 'unknown', 'confidence': 0.0, 'reasons': [reason]} for s in SQUARES}


def classify(image_rectified, calibration):
    """Return {square: {label, confidence, reasons, ...}} with label in empty/white/black/unknown."""
    raw, smooth = _prepare(image_rectified)
    empty_ref = [np.asarray(r) for r in calibration['emptyRef']]
    piece_ref = {(k.split('-')[0], int(k.endswith('dark'))): np.asarray(v) for k, v in calibration['pieceRef'].items()}
    tiles, raw_tiles = _tiles(smooth), _tiles(raw)
    # Per-frame lighting correction: map this frame's light/dark border medians onto the calibrated ones.
    observed = [np.median(np.concatenate([tiles[i][_BORDER] for i in range(64) if DARK[i] == p]), axis=0)
                for p in (0, 1)]
    span = observed[0] - observed[1]
    if np.any(np.abs(span) < 1e-6):
        return _abstain_all('lighting-out-of-range')
    gain = (empty_ref[0] - empty_ref[1]) / span
    offset = empty_ref[0] - gain * observed[0]
    if not np.all((gain >= GAIN_RANGE[0]) & (gain <= GAIN_RANGE[1])):
        return _abstain_all('lighting-out-of-range')
    if _sharpness(smooth) < FRAME_SHARPNESS_MIN * calibration['boundarySharpness']:
        return _abstain_all('frame-too-blurry')  # blur fakes the lighting correction (v2 gate)
    out = {}
    for i in range(64):
        tile = tiles[i] * gain + offset
        parity = DARK[i]
        fg, border, colour = _measure(tile, empty_ref[parity])
        saturated = float((raw_tiles[i].min(axis=2) >= SATURATED_LEVEL).mean())
        reasons, scores = [], {}
        scores['border'] = _clamp(1 - border / (2 * BORDER_MAX_FRAC))
        scores['saturation'] = _clamp(1 - saturated / (2 * SATURATED_MAX_FRAC))
        if fg <= EMPTY_MAX_FG:
            scores['occupancy'] = _clamp(0.5 + 0.5 * (EMPTY_MAX_FG - fg) / EMPTY_MAX_FG)
        elif fg >= PIECE_MIN_FG:
            scores['occupancy'] = _clamp(0.5 + 0.5 * (fg - PIECE_MIN_FG) / PIECE_MIN_FG)
        else:  # inside the ambiguous band: 0.5 at either edge, 0 in the middle
            half = (PIECE_MIN_FG - EMPTY_MAX_FG) / 2
            scores['occupancy'] = _clamp(0.5 * abs(fg - (EMPTY_MAX_FG + half)) / half)
        if border > BORDER_MAX_FRAC:
            reasons.append('background-mismatch')
        if saturated > SATURATED_MAX_FRAC:
            reasons.append('saturated-pixels')
        if EMPTY_MAX_FG < fg < PIECE_MIN_FG:
            reasons.append('ambiguous-occupancy')
        label = 'empty' if fg <= EMPTY_MAX_FG else 'piece'
        if label == 'piece':
            if colour is None:
                reasons.append('no-foreground-colour'); scores['colour'] = 0.0
            else:
                label, share, dist = _colour_vote(colour, piece_ref[('white', parity)], piece_ref[('black', parity)])
                # vote share COLOR_VOTE_MIN -> 0.5, unanimous -> 1; distance COLOR_MAX_DIST -> 0.5
                scores['colour'] = min(_clamp(0.5 + 0.5 * (share - COLOR_VOTE_MIN) / (1 - COLOR_VOTE_MIN)),
                                       _clamp(1 - dist / (2 * COLOR_MAX_DIST)))
                if share < COLOR_VOTE_MIN:
                    reasons.append('ambiguous-colour')
                if dist > COLOR_MAX_DIST:
                    reasons.append('unfamiliar-foreground-colour')
        confidence = min(scores.values())
        if reasons or confidence < ABSTAIN_BELOW:
            reasons = reasons or ['low-confidence']
            out[SQUARES[i]] = {'label': 'unknown', 'rawLabel': label, 'confidence': round(confidence, 4),
                               'reasons': reasons}
        else:
            out[SQUARES[i]] = {'label': label, 'rawLabel': label, 'confidence': round(confidence, 4), 'reasons': []}
        out[SQUARES[i]].update({'fgFrac': round(fg, 4), 'borderFrac': round(border, 4),
                                'saturatedFrac': round(saturated, 4)})
    return out


def classify_image(image, calibration, shift=(0, 0)):
    """Rectify then classify; geometry failure -> all unknown. shift = (dx, dy) misregistration in panel px."""
    try:
        panel = rectify(image)
    except ValueError as error:
        return _abstain_all(f'geometry:{error}'), False
    if shift != (0, 0):
        arr = np.asarray(panel)
        arr = np.roll(arr, shift=(shift[1], shift[0]), axis=(0, 1))
        panel = Image.fromarray(arr, 'RGB')
    return classify(panel, calibration), True


# -------------------------------------------------------------- evaluation ----
START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR'
# Frame categories, fixed before scoring. Every corpus frame has mild camera jitter, so
# "perspective" means the stronger keystones (side-length ratio >= 1.04).
PERSPECTIVE_SIDE_RATIO = 1.04
LIGHTING_DELTA = 0.04


def _truth_label(ch):
    return 'empty' if ch == '.' else ('white' if ch.isupper() else 'black')


def category(frame):
    scene = frame['scene']
    if frame['split'] == 'challenge':
        return 'occlusion/challenge'
    if abs(scene.get('brightness', 1) - 1) >= LIGHTING_DELTA or scene.get('boardVariation'):
        return 'lighting'
    q = np.asarray(scene['quad'], float)
    side = lambda a, b: np.linalg.norm(q[a] - q[b])  # noqa: E731
    ratio = max(max(side(0, 1), side(3, 2)) / min(side(0, 1), side(3, 2)),
                max(side(0, 3), side(1, 2)) / min(side(0, 3), side(1, 2)))
    return 'perspective' if ratio >= PERSPECTIVE_SIDE_RATIO else 'clean'


def score(result, frame):
    c = w = a = 0
    wrong = []
    for s in SQUARES:
        truth = _truth_label(frame['squares'][s])
        got = result[s]['label']
        if got == 'unknown':
            a += 1
        elif got == truth:
            c += 1
        else:
            w += 1; wrong.append({'square': s, 'truth': truth, 'got': got, 'confidence': result[s]['confidence']})
    return {'correct': c, 'wrong': w, 'abstained': a, 'allCorrect': c == 64, 'wrongSquares': wrong}


def _empty_tally():
    return {'frames': 0, 'squares': 0, 'correct': 0, 'wrong': 0, 'abstained': 0, 'framesAll64Correct': 0,
            'framesNoWrong': 0}


def _add(t, s):
    t['frames'] += 1; t['squares'] += 64
    for k in ('correct', 'wrong', 'abstained'):
        t[k] += s[k]
    t['framesAll64Correct'] += s['allCorrect']; t['framesNoWrong'] += s['wrong'] == 0


def _load_corpus(corpus):
    corpus = Path(corpus)
    truth = json.loads((corpus / 'evaluator/truth.json').read_text())
    return corpus / 'pixels', truth


def _session_plan(truth):
    """Which frame calibrates each session. Standard-start sessions use their own first frame;
    sessions that do not start from the standard start (or whose start is rejected) borrow dev-opening's."""
    frames_by_session = {}
    for f in truth['frames']:
        frames_by_session.setdefault(f['session'], []).append(f)
    return frames_by_session


def evaluate(corpus, out, splits):
    pixels, truth = _load_corpus(corpus)
    sessions = _session_plan(truth)
    calibrations, cal_log = {}, []
    dev_first = sessions['dev-opening'][0]
    base = calibrate(rectify(pixels / dev_first['file']), occupancy_from_fen(dev_first['fen']))
    tallies, frames_out = {}, []
    for sid, frames in sessions.items():
        split = frames[0]['split']
        if split not in splits:
            continue
        first = frames[0]
        own = first['fen'].split()[0] == START_FEN
        cal, source, scored = base, 'borrowed:dev-opening/' + dev_first['id'], frames
        if own:
            try:
                cal = calibrate(rectify(pixels / first['file']), occupancy_from_fen(first['fen']))
                source, scored = 'own-first-frame/' + first['id'], frames[1:]
            except (CalibrationError, ValueError) as error:
                source = f'borrowed:dev-opening/{dev_first["id"]} (own start rejected: {error})'
                if sid == 'dev-opening':
                    scored = frames[1:]
        cal_log.append({'session': sid, 'split': split, 'calibration': source, 'scoredFrames': len(scored)})
        for f in scored:
            result, geometry_ok = classify_image(pixels / f['file'], cal)
            s = score(result, f)
            cat = category(f)
            for key in (f'{split}|all', f'{split}|{cat}', 'all|all'):
                _add(tallies.setdefault(key, _empty_tally()), s)
            frames_out.append({'id': f['id'], 'session': sid, 'split': split, 'category': cat,
                               'geometry': geometry_ok, **{k: s[k] for k in ('correct', 'wrong', 'abstained')},
                               'wrongSquares': s['wrongSquares'],
                               'abstainReasons': sorted({r for v in result.values() for r in v['reasons']})})
    report = {'policy': policy(), 'categoryRules': {'perspectiveSideRatio': PERSPECTIVE_SIDE_RATIO,
                                                    'lightingDelta': LIGHTING_DELTA},
              'splits': sorted(splits), 'calibrations': cal_log, 'tallies': tallies, 'frames': frames_out}
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    name = 'evaluation-' + '-'.join(sorted(splits)) + '.json'
    (out / name).write_text(json.dumps(report, indent=1))
    return report


# --------------------------------------------------------------- sweep ----
def _jpeg(img, q):
    buf = io.BytesIO(); img.save(buf, format='JPEG', quality=q); buf.seek(0)
    return Image.open(buf).convert('RGB')


def _noise(img, sigma, seed):
    arr = np.asarray(img, float) + np.random.default_rng(seed).normal(0, sigma, (img.height, img.width, 3))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), 'RGB')


def _gamma(img, g):
    arr = 255 * (np.asarray(img, float) / 255) ** g
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), 'RGB')


def _brightness(img, k):
    return Image.fromarray(np.clip(np.asarray(img, float) * k, 0, 255).astype(np.uint8), 'RGB')


def _glare(img, radius, seed):
    """Soft near-white specular blob at a deterministic spot over the board area."""
    rng = np.random.default_rng(seed)
    cx, cy = rng.uniform(180, 590), rng.uniform(180, 590)
    yy, xx = np.mgrid[0:img.height, 0:img.width]
    alpha = np.clip(1.4 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * (radius / 2) ** 2)), 0, 1)[..., None]
    arr = np.asarray(img, float) * (1 - alpha) + 255 * alpha
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), 'RGB')


PERTURBATIONS = [
    ('none', {}),
    ('brightness', {'k': 0.7}), ('brightness', {'k': 0.85}), ('brightness', {'k': 1.15}), ('brightness', {'k': 1.3}),
    ('gamma', {'g': 0.6}), ('gamma', {'g': 1.6}),
    ('blur', {'r': 1.0}), ('blur', {'r': 2.0}), ('blur', {'r': 3.0}),
    ('jpeg', {'q': 70}), ('jpeg', {'q': 50}), ('jpeg', {'q': 30}),
    ('noise', {'sigma': 8}), ('noise', {'sigma': 16}), ('noise', {'sigma': 24}),
    ('glare', {'radius': 40}), ('glare', {'radius': 90}),
    ('misregister', {'dx': 1, 'dy': 0}), ('misregister', {'dx': 2, 'dy': 0}), ('misregister', {'dx': 2, 'dy': 2}),
    # Stress levels beyond the brief, added after the sweep above showed no wrong-confident squares,
    # to find where the classifier starts to fail. Thresholds were not changed.
    ('brightness', {'k': 0.5}), ('blur', {'r': 5.0}), ('noise', {'sigma': 40}),
    ('misregister', {'dx': 4, 'dy': 4}), ('misregister', {'dx': 8, 'dy': 0}), ('misregister', {'dx': 16, 'dy': 0}),
]


def _perturb(img, kind, p, seed):
    if kind == 'brightness': return _brightness(img, p['k'])
    if kind == 'gamma': return _gamma(img, p['g'])
    if kind == 'blur': return img.filter(ImageFilter.GaussianBlur(p['r']))
    if kind == 'jpeg': return _jpeg(img, p['q'])
    if kind == 'noise': return _noise(img, p['sigma'], seed)
    if kind == 'glare': return _glare(img, p['radius'], seed)
    return img


def sweep(corpus, out, save_examples=True):
    """Perturb clean dev standard-start frames; calibration stays on the unperturbed first frame."""
    pixels, truth = _load_corpus(corpus)
    sessions = _session_plan(truth)
    rows = []
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    examples = out / 'sweep-examples'
    plan = []
    for sid in ('dev-opening', 'fixture-repetition'):
        frames = sessions[sid]
        cal = calibrate(rectify(pixels / frames[0]['file']), occupancy_from_fen(frames[0]['fen']))
        plan.extend((cal, f) for f in frames[1:])
    def run(kind, params, stage):
        t = _empty_tally(); geometry_fail = 0; wrong_conf = []
        for n, (cal, f) in enumerate(plan):
            img = Image.open(pixels / f['file']).convert('RGB')
            shift = (params['dx'], params['dy']) if kind == 'misregister' else (0, 0)
            if stage == 'image':  # perturb the camera image, then locate + rectify + classify
                img = _perturb(img, kind, params, seed=1000 + n)
                if save_examples and n == 0 and kind != 'none':
                    examples.mkdir(exist_ok=True)
                    img.save(examples / f"{kind}-{'-'.join(f'{k}{v}' for k, v in params.items())}.png")
                result, ok = classify_image(img, cal, shift)
            else:  # 'panel': geometry from the clean image; perturb only what the classifier sees
                panel = _perturb(rectify(img), kind, params, seed=1000 + n)
                result, ok = classify(panel, cal), True
            geometry_fail += not ok
            sc = score(result, f); _add(t, sc)
            wrong_conf.extend({'frame': f['id'], **w} for w in sc['wrongSquares'])
        rows.append({'perturbation': kind, 'params': params, 'stage': stage, 'geometryFailures': geometry_fail,
                     **t, 'wrongConfidentRate': t['wrong'] / t['squares'],
                     'abstainRate': t['abstained'] / t['squares'], 'wrongExamples': wrong_conf[:10]})
        return geometry_fail

    for kind, params in PERTURBATIONS:
        if run(kind, params, 'image'):
            run(kind, params, 'panel')  # geometry broke: also measure the classifier on its own
    report = {'policy': policy(), 'frames': len(plan), 'rows': rows}
    (out / 'sweep.json').write_text(json.dumps(report, indent=1))
    return report


def _print_eval(report):
    print('calibrations:')
    for c in report['calibrations']:
        print(f"  {c['session']:28s} {c['split']:9s} scored={c['scoredFrames']:2d}  {c['calibration']}")
    print(f"{'split|category':30s} frames squares correct wrong(confident) abstained all64 noWrong")
    for k in sorted(report['tallies']):
        t = report['tallies'][k]
        print(f"{k:30s} {t['frames']:6d} {t['squares']:7d} {t['correct']:7d} {t['wrong']:16d} {t['abstained']:9d}"
              f" {t['framesAll64Correct']:5d} {t['framesNoWrong']:7d}")


def _print_sweep(report):
    print(f"frames per level: {report['frames']}")
    print(f"{'perturbation':28s} geomFail correct wrong abstain wrongRate abstainRate all64")
    for r in report['rows']:
        name = r['perturbation'] + ' ' + ','.join(f'{k}={v}' for k, v in r['params'].items()) + \
            (' [panel]' if r['stage'] == 'panel' else '')
        print(f"{name:28s} {r['geometryFailures']:8d} {r['correct']:7d} {r['wrong']:5d} {r['abstained']:7d}"
              f" {r['wrongConfidentRate']:9.4f} {r['abstainRate']:11.4f} {r['framesAll64Correct']:5d}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=['evaluate', 'sweep'])
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--split', default='dev', choices=['dev', 'heldout', 'challenge', 'all'])
    args = parser.parse_args()
    if args.mode == 'evaluate':
        splits = {'dev', 'heldout', 'challenge'} if args.split == 'all' else {args.split}
        _print_eval(evaluate(args.corpus, args.out, splits))
    else:
        _print_sweep(sweep(args.corpus, args.out))
