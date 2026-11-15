#!/usr/bin/env python3
"""Square reader v3: EMPTY / WHITE / BLACK / UNKNOWN per square (experiment, not app code).

Same public API as occupancy_classifier.py (v2, frozen): calibrate(start_panel, occupancy),
classify(panel, calibration), occupancy_from_fen, CalibrationError, policy(), SQUARES, plus the
marker-corpus helpers rectify / classify_image used by the original tests.

What changed versus v2 (see docs/OCCUPANCY_CLASSIFIER_V3.md):
  1. Local lighting. After v2's global light/dark correction, each square gets its own row-by-row
     correction measured on its left and right bare-board strips and fitted with a physical model
     (banding = brightness factor of a few per cent, glare = added grey light). Only the fitted
     lighting is removed, so an occluder or hand stays visible. Large, sharp or unexplained local
     changes are gates; a square next to a sharp lighting edge is also unknown (occluder edges).
  2. Two independent occupancy cues must agree: colour difference from the locally corrected board
     AND vertical-edge evidence (piece outlines). Banding and glare are smooth and near-horizontal in
     the panel, so they cannot fake vertical edges; disagreement is unknown, never piece or empty.
  3. Colour: v2's depth-weighted core vote, but the silhouette is closed over 1-2 px outline gaps,
     at least 40 core pixels are required (outline-only silhouettes read as the wrong colour), and the
     white/black references are the bright/dark halves of the start pieces' core pixels.
  4. Calibration uses the same measurement (a banded start passes only if every square passes the
     normal gates after local correction); the stated colour must win each square by 0.60 and average
     0.85 per colour (the black queen sat near v2's 0.75). Clipped white piece fill is allowed when the
     square's ring is unclipped and its local lighting is calm. Global gain range widened to 0.33-3.0.
"""
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
import recognize as _geometry  # noqa: E402  (marker geometry for the original corpus only)
from appearance import BOARD_ORIGIN, TILE_SIZE  # noqa: E402

SQUARES = ['abcdefgh'[i % 8] + str(8 - i // 8) for i in range(64)]
DARK = [(i // 8 + i % 8) % 2 for i in range(64)]  # a8 light, a1 dark
LABELS = ('empty', 'white', 'black', 'unknown')
VERSION = 'v3'

# ---- Policy. Every threshold is here and returned by policy(). Development data only. ----
PRE_BLUR_RADIUS = 1.0         # Gaussian denoise before pixel tests (v2)
GAIN_RANGE = (0.33, 3.0)      # global light/dark correction allowed relative to calibration (v2: 0.5-2.0)
FRAME_SHARPNESS_MIN = 0.4     # square-boundary contrast vs calibration; below = whole frame unknown (v2)
FG_DISTANCE = 40.0            # RGB distance from the locally corrected board that counts as "not board" (v2)
EMPTY_MAX_FG = 0.03           # foreground share of the window at or below which the colour cue says empty (v2)
PIECE_MIN_FG = 0.08           # ... at or above which it says occupied (v2)
EDGE_LEVEL = 0.22             # |horizontal luminance step| per px, as a share of light/dark contrast, = an edge pixel
EMPTY_MAX_EDGE = 0.005        # edge share of the window at or below which the edge cue says empty
PIECE_MIN_EDGE = 0.015        # ... at or above which it says occupied
BORDER_MAX_FRAC = 0.20        # ring pixels allowed to differ from the locally corrected board (v2 value)
LOCAL_SMOOTH_ROWS = 7         # rows averaged when measuring the per-row correction on the side strips
LOCAL_MAX_SHIFT = 0.60        # largest per-row local correction (luminance, share of contrast) still trusted
LOCAL_MAX_STEP = 0.12         # largest change of that correction between neighbouring rows (share of contrast)
LOCAL_MAX_UNEXPLAINED = 0.30  # strip colour change the lighting model cannot explain (share of contrast)
LOCAL_MAX_MULT = 0.20         # largest brightness factor change |k| (banding is a few per cent to ~15 %)
LOCAL_MAX_DARK_HAZE = 0.25    # glare only adds light: a negative haze term beyond this share of contrast is not lighting
LOCAL_SIDE_MAX = 0.40         # left vs right strip correction disagreement allowed (share of contrast)
NEIGHBOUR_RULE = 1            # 1: a square next to (8-neighbourhood) a square with a sharp lighting edge is unknown
SATURATED_LEVEL = 250         # all three raw channels at or above this = clipped (v2)
SATURATED_MAX_FRAC = 0.05     # clipped share of the square that forces abstention unless explained (v2)
SATURATED_OK_MAX_SHIFT = 0.15 # ... unless local lighting is calm (undisturbed dev max 0.14) ...
SATURATED_OK_MAX_RING = 0.02  # ... and the bare-board ring itself is not clipped (then it is a white piece's fill)
COLOUR_MAX_ROW = 46           # colour read only above this tile row (piece body, not its base) (v2)
SIL_CLOSE_PX = 2              # silhouette = outline closed over gaps up to ~2x this many px, holes filled
CORE_MIN_DEPTH = 2            # colour read only >= this many px inside the filled silhouette (v2) ...
CORE_DEPTH_BAND = 3           # ... and within this many px of its deepest point (v2)
FILL_EDGE_GUARD = -1          # -1 off; 0 = drop edge pixels from the core; n = also drop pixels within n px
MIN_FILL_PIXELS = 40          # core pixels needed to name a colour (v2: 6; outline-only silhouettes have < 40)
COLOR_VOTE_MIN = 0.75         # share of fill pixels that must vote for one colour (v2 value)
CAL_VOTE_MIN = 0.60           # calibration only: the STATED colour must win each square by this share ...
CAL_VOTE_MEAN_MIN = 0.85      # ... and average this share over all pieces of that colour (the start is human-confirmed)
COLOR_MAX_DIST = 70.0         # median fill-pixel distance to the nearer fill reference above this = unfamiliar (v2)
COLOR_MIN_SEPARATION = 0.35   # calibration: white and black fill luminance must differ by this share of 255
MIN_SAMPLES_PER_CLASS = 2     # squares needed for each reference (v2)
ABSTAIN_BELOW = 0.5           # every component score is scaled so its gate sits at 0.5 (v2)

_T = TILE_SIZE
_BORDER = np.zeros((_T, _T), dtype=bool)
_BORDER[3:7, 3:-3] = True; _BORDER[-7:-3, 3:-3] = True
_BORDER[3:-3, 3:7] = True; _BORDER[3:-3, -7:-3] = True
_TOPBOT = np.zeros((_T, _T), dtype=bool)
_TOPBOT[3:7, 8:-8] = True; _TOPBOT[-7:-3, 8:-8] = True
_WINDOW = np.zeros((_T, _T), dtype=bool)
_WINDOW[8:58, 12:52] = True
_LEFT = slice(3, 8)
_RIGHT = slice(_T - 8, _T - 3)
_ROWS = slice(3, _T - 3)
_LUM = np.array([0.299, 0.587, 0.114])


class CalibrationError(ValueError):
    """The supposedly confirmed start frame does not match its stated occupancy."""


def policy():
    return {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float, tuple, str))
            and not k.startswith('_') and k not in ('TILE_SIZE',)}


# ---------------------------------------------------------------- geometry (marker corpus) ----
def rectify(image):
    """Image (PIL or path) -> 640x640 rectified panel using visible markers (original corpus). Raises ValueError."""
    if not isinstance(image, Image.Image):
        image = Image.open(image)
    image = image.convert('RGB')
    try:
        panel, _ = _geometry._rectify(image, _geometry._markers(image))
    except np.linalg.LinAlgError as error:
        raise ValueError('geometry-unavailable') from error
    return panel


def occupancy_from_fen(fen):
    rows, out = fen.split()[0].split('/'), []
    for row in rows:
        for ch in row:
            out.extend(['empty'] * int(ch) if ch.isdigit() else ['white' if ch.isupper() else 'black'])
    if len(out) != 64:
        raise ValueError('bad placement')
    return dict(zip(SQUARES, out))


def _prepare(panel):
    if isinstance(panel, np.ndarray):
        panel = Image.fromarray(np.clip(panel, 0, 255).astype(np.uint8), 'RGB')
    panel = panel.convert('RGB')
    raw = np.asarray(panel, dtype=float)
    smooth = np.asarray(panel.filter(ImageFilter.GaussianBlur(PRE_BLUR_RADIUS)), dtype=float)
    return raw, smooth


def _tiles(pixels):
    x, y = BOARD_ORIGIN
    return [pixels[y + r * _T:y + (r + 1) * _T, x + c * _T:x + (c + 1) * _T] for r in range(8) for c in range(8)]


def _clamp(v):
    return float(min(1.0, max(0.0, v)))


def _sharpness(pixels):
    """v2's boundary sharpness: steepest 3-px light/dark step at square boundaries / step 8 px either side."""
    lum = pixels.mean(axis=2)
    x0, y0 = BOARD_ORIGIN
    ratios = []
    for r in range(8):
        rows = slice(y0 + r * _T + 4, y0 + r * _T + 12)
        for c in range(1, 8):
            x = x0 + c * _T
            near = max(abs(lum[rows, x + o - 2].mean() - lum[rows, x + o + 1].mean()) for o in range(-4, 5))
            far = abs(lum[rows, x - 9].mean() - lum[rows, x + 8].mean())
            if far > 10:
                ratios.append(near / far)
    return float(np.median(ratios)) if ratios else 0.0


def _fill_holes(mask):
    outside = np.zeros_like(mask)
    outside[0, :] = outside[-1, :] = outside[:, 0] = outside[:, -1] = True
    outside &= ~mask
    for _ in range(_T * 4):
        grown = outside.copy()
        grown[1:] |= outside[:-1]; grown[:-1] |= outside[1:]
        grown[:, 1:] |= outside[:, :-1]; grown[:, :-1] |= outside[:, 1:]
        grown &= ~mask
        if (grown == outside).all():
            break
        outside = grown
    return ~outside


def _deep_core(fg):
    """v2: pixels within CORE_DEPTH_BAND of the deepest point of the hole-filled silhouette, depth >= CORE_MIN_DEPTH."""
    current = _fill_holes(_dilate(fg, SIL_CLOSE_PX)) if SIL_CLOSE_PX else _fill_holes(fg)
    for _ in range(SIL_CLOSE_PX):  # erode back: a closing, so a 1-2 px gap in an outline no longer leaks
        current = np.asarray(Image.fromarray(current.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(3))) > 0
    depth = np.zeros(fg.shape, dtype=int)
    for level in range(1, 20):
        current = np.asarray(Image.fromarray(current.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(3))) > 0
        if not current.any():
            break
        depth[current] = level
    floor = max(CORE_MIN_DEPTH, int(depth.max()) - CORE_DEPTH_BAND)
    return np.where(depth >= floor, depth - floor + 1, 0)  # weight: 1 at the band floor, more deeper in (v2)


def _dilate(mask, n):
    out = mask.copy()
    for _ in range(n):
        g = out.copy()
        g[1:] |= out[:-1]; g[:-1] |= out[1:]; g[:, 1:] |= out[:, :-1]; g[:, :-1] |= out[:, 1:]
        out = g
    return out


def _running_mean(values, n):
    """Centred running mean along axis 0 with edge padding (values: rows x channels)."""
    pad = n // 2
    v = np.concatenate([np.repeat(values[:1], pad, 0), values, np.repeat(values[-1:], pad, 0)])
    c = np.cumsum(np.concatenate([np.zeros((1,) + v.shape[1:]), v]), axis=0)
    return (c[n:] - c[:-n]) / n


# ---------------------------------------------------------------- per-square measurement ----
def _lighting_fit(delta, ref, contrast):
    """Fit each row of delta (rows x 3) as k * ref + b * grey with |k| <= LOCAL_MAX_MULT and
    b >= -LOCAL_MAX_DARK_HAZE * contrast (banding scales the board colour by a few per cent; glare only adds
    light). Box-constrained least squares, solved exactly by trying every active set. Returns (fit, residual norm)."""
    kmax, bmin = LOCAL_MAX_MULT, -LOCAL_MAX_DARK_HAZE * contrast
    rr, r1, n1 = float(ref @ ref), float(ref.sum()), 3.0
    dr, d1 = delta @ ref, delta.sum(axis=1)
    det = rr * n1 - r1 * r1
    cands = []
    k0 = (dr * n1 - d1 * r1) / det
    b0 = (rr * d1 - r1 * dr) / det
    cands.append((k0, b0, (np.abs(k0) <= kmax) & (b0 >= bmin)))
    for kf in (-kmax, kmax):  # k on a bound, best b
        bb = (d1 - kf * r1) / n1
        cands.append((np.full_like(bb, kf), bb, bb >= bmin))
    kk = (dr - bmin * r1) / rr  # b on its bound, best k
    cands.append((kk, np.full_like(kk, bmin), np.abs(kk) <= kmax))
    for kf in (-kmax, kmax):  # both on bounds
        cands.append((np.full_like(dr, kf), np.full_like(dr, bmin), np.ones_like(dr, dtype=bool)))
    best_fit, best_res = None, None
    for k, b, ok in cands:
        fit = k[:, None] * ref[None, :] + b[:, None]
        res = np.where(ok, np.linalg.norm(delta - fit, axis=1), np.inf)
        if best_res is None:
            best_fit, best_res = fit, res
        else:
            better = res < best_res
            best_fit = np.where(better[:, None], fit, best_fit)
            best_res = np.where(better, res, best_res)
    return best_fit, best_res


def _local_correction(tile, ref, contrast):
    """Row-by-row board correction from the square's own left/right bare strips.

    Each smoothed strip row's difference from the board colour is fitted with a physical lighting model
    (_lighting_fit: banding = brightness factor, glare = added grey light). The offset applied to the square
    is the FITTED lighting, interpolated left to right, so anything the model cannot express (an occluder,
    a hand, a different colour) stays visible in the corrected tile and in 'unexplained'.
    """
    left = _running_mean(np.median(tile[_ROWS, _LEFT], axis=1) - ref, LOCAL_SMOOTH_ROWS)    # rows x 3
    right = _running_mean(np.median(tile[_ROWS, _RIGHT], axis=1) - ref, LOCAL_SMOOTH_ROWS)
    fit_l, res_l = _lighting_fit(left, ref, contrast)
    fit_r, res_r = _lighting_fit(right, ref, contrast)
    pad = (_T - left.shape[0]) // 2
    full_l = np.concatenate([np.repeat(fit_l[:1], pad, 0), fit_l, np.repeat(fit_l[-1:], pad, 0)])
    full_r = np.concatenate([np.repeat(fit_r[:1], pad, 0), fit_r, np.repeat(fit_r[-1:], pad, 0)])
    w = np.clip((np.arange(_T) - 5.0) / (_T - 11.0), 0, 1)[None, :, None]
    offset = full_l[:, None, :] * (1 - w) + full_r[:, None, :] * w
    lum_l, lum_r = fit_l @ _LUM, fit_r @ _LUM
    return offset, {
        'shift': float(np.max(np.abs(np.concatenate([lum_l, lum_r])))) / contrast,
        'step': float(max(np.max(np.abs(np.diff(lum_l))), np.max(np.abs(np.diff(lum_r))))) / contrast,
        'side': float(np.max(np.abs(lum_l - lum_r))) / contrast,
        'unexplained': float(max(res_l.max(), res_r.max())) / contrast}


def _edges(tile, contrast):
    """Horizontal luminance steps (vertical edges) above EDGE_LEVEL x contrast."""
    lum = tile @ _LUM
    g = np.zeros_like(lum)
    g[:, 1:-1] = np.abs(lum[:, 2:] - lum[:, :-2]) / 2
    return g > EDGE_LEVEL * contrast


def _measure(tile, ref, contrast):
    offset, local = _local_correction(tile, ref, contrast)
    corrected = tile - offset
    dist = np.linalg.norm(corrected - ref, axis=2)
    fg = (dist > FG_DISTANCE) & _WINDOW
    fg_frac = float(fg.sum() / _WINDOW.sum())
    border_frac = float((dist[_TOPBOT] > FG_DISTANCE).mean())
    edges = _edges(tile, contrast)
    edge_frac = float((edges & _WINDOW).sum() / _WINDOW.sum())
    fill = None
    if fg.sum() >= MIN_FILL_PIXELS:
        weights = _deep_core(fg)
        if FILL_EDGE_GUARD >= 0:
            weights[_dilate(edges, FILL_EDGE_GUARD) if FILL_EDGE_GUARD else edges] = 0
        weights[COLOUR_MAX_ROW:] = 0
        core = weights > 0
        if core.sum() >= MIN_FILL_PIXELS:
            fill = (corrected[core], weights[core].astype(float))
    return {'fg': fg_frac, 'border': border_frac, 'edge': edge_frac, 'fill': fill, 'local': local}


def _vote(fill, white_ref, black_ref):
    """Depth-weighted vote of core pixels for the nearer fill reference (v2 rule, v3 references)."""
    fill, weights = fill
    d_w = np.linalg.norm(fill - white_ref, axis=1)
    d_b = np.linalg.norm(fill - black_ref, axis=1)
    white_share = float(weights[d_w < d_b].sum() / weights.sum())
    label = 'white' if white_share >= 0.5 else 'black'
    return label, max(white_share, 1 - white_share), float(np.median(np.minimum(d_w, d_b)))


def _occupancy_cues(m):
    if m['fg'] <= EMPTY_MAX_FG:
        fg_cue = 'empty'
    elif m['fg'] >= PIECE_MIN_FG:
        fg_cue = 'piece'
    else:
        fg_cue = 'ambiguous'
    if m['edge'] <= EMPTY_MAX_EDGE:
        edge_cue = 'empty'
    elif m['edge'] >= PIECE_MIN_EDGE:
        edge_cue = 'piece'
    else:
        edge_cue = 'ambiguous'
    return fg_cue, edge_cue


def _saturation(raw_tile, local):
    """(clipped share of the square, True if that clipping forces abstention). Clipping inside the window of a
    square whose ring is unclipped and whose local lighting is calm is a bright white piece (allowed); clipping
    on the ring, or under a glare/stripe, can hide what is there (abstain)."""
    clipped = raw_tile.min(axis=2) >= SATURATED_LEVEL
    frac = float(clipped.mean())
    if frac <= SATURATED_MAX_FRAC:
        return frac, False
    calm = local['shift'] <= SATURATED_OK_MAX_SHIFT and float(clipped[_BORDER].mean()) <= SATURATED_OK_MAX_RING
    return frac, not calm


def _sharp_lighting(local):
    """A lighting change with a sharp edge inside the square (between rows, or left vs right): the edge of an
    occluder or a hard shadow, not smooth glare or banding. Its neighbours may be covered without showing it."""
    return local['step'] > LOCAL_MAX_STEP or local['side'] > LOCAL_SIDE_MAX


def _local_reasons(local):
    reasons = []
    if local['shift'] > LOCAL_MAX_SHIFT:
        reasons.append('local-lighting-too-strong')
    if local['step'] > LOCAL_MAX_STEP:
        reasons.append('local-lighting-stripe')
    if local['side'] > LOCAL_SIDE_MAX:
        reasons.append('local-lighting-uneven')
    if local['unexplained'] > LOCAL_MAX_UNEXPLAINED:
        reasons.append('local-change-is-not-lighting')
    return reasons


# ------------------------------------------------------------- calibration ----
def _empty_refs(tiles, occ):
    refs = []
    for parity in (0, 1):
        idx = [i for i in range(64) if occ[i] == 'empty' and DARK[i] == parity]
        if len(idx) < MIN_SAMPLES_PER_CLASS:
            raise CalibrationError(f'too-few-empty-{"dark" if parity else "light"}-squares')
        refs.append(np.median(np.concatenate([tiles[i][_BORDER | _WINDOW] for i in idx]), axis=0))
    return refs


def calibrate(start_image_rectified, start_occupancy):
    """Learn board and piece-fill references from one confirmed frame; reject if any square disagrees.

    start_occupancy: {square: 'empty'|'white'|'black'} for all 64 squares in panel tile order.
    """
    if set(start_occupancy) != set(SQUARES) or not set(start_occupancy.values()) <= {'empty', 'white', 'black'}:
        raise CalibrationError('occupancy must label all 64 squares empty/white/black')
    raw, smooth = _prepare(start_image_rectified)
    tiles, raw_tiles = _tiles(smooth), _tiles(raw)
    occ = [start_occupancy[s] for s in SQUARES]
    empty_ref = _empty_refs(tiles, occ)
    contrast = float(abs((empty_ref[0] - empty_ref[1]) @ _LUM))
    if contrast < 10:
        raise CalibrationError('light-and-dark-squares-indistinguishable')
    measures = [_measure(tiles[i], empty_ref[DARK[i]], contrast) for i in range(64)]
    fills = {}
    for colour in ('white', 'black'):
        idx = [i for i in range(64) if occ[i] == colour and measures[i]['fill'] is not None]
        if len(idx) < MIN_SAMPLES_PER_CLASS:
            raise CalibrationError(f'too-few-{colour}-pieces-with-readable-fill')
        fills[colour] = np.concatenate([measures[i]['fill'][0] for i in idx])
    # Fill references: the piece fill is the majority tone of each colour's pixels. Take the median of the
    # brighter half for white and of the darker half for black, so outline pixels (opposite tone) do not drag it.
    lw = fills['white'] @ _LUM
    lb = fills['black'] @ _LUM
    white_ref = np.median(fills['white'][lw >= np.median(lw)], axis=0)
    black_ref = np.median(fills['black'][lb <= np.median(lb)], axis=0)
    problems, shares = [], {}
    if (white_ref - black_ref) @ _LUM < COLOR_MIN_SEPARATION * 255:
        problems.append(('*', 'white-fill-not-lighter-than-black'))
    for i, m in enumerate(measures):
        reasons = _local_reasons(m['local'])
        if _saturation(raw_tiles[i], m['local'])[1]:
            reasons.append('saturated-pixels')
        if m['border'] > BORDER_MAX_FRAC:
            reasons.append('background-mismatch')
        fg_cue, edge_cue = _occupancy_cues(m)
        if occ[i] == 'empty':
            if fg_cue != 'empty' or edge_cue != 'empty':
                reasons.append('stated-empty-but-occupied')
        elif fg_cue != 'piece' or edge_cue != 'piece' or m['fill'] is None:
            reasons.append('stated-occupied-but-empty')
        else:
            label, share, dist = _vote(m['fill'], white_ref, black_ref)
            if label != occ[i] or share < CAL_VOTE_MIN or dist > COLOR_MAX_DIST:
                reasons.append(f'stated-{occ[i]}-colour-mismatch')
            else:
                shares.setdefault(occ[i], []).append(share)
        if reasons:
            problems.append((SQUARES[i], reasons[0]))
    for colour, values in shares.items():
        if np.mean(values) < CAL_VOTE_MEAN_MIN:
            problems.append(('*', f'{colour}-pieces-colour-vote-weak'))
    if problems:
        raise CalibrationError(f'{len(problems)} square(s) disagree with stated occupancy: '
                               + ', '.join(f'{s}:{r}' for s, r in problems[:8]))
    return {'version': VERSION, 'emptyRef': [r.tolist() for r in empty_ref], 'contrast': contrast,
            'boundarySharpness': _sharpness(smooth), 'fillRef': {'white': white_ref.tolist(),
                                                                'black': black_ref.tolist()},
            'policy': policy()}


# ---------------------------------------------------------- classification ----
def _abstain_all(reason):
    return {s: {'label': 'unknown', 'confidence': 0.0, 'reasons': [reason]} for s in SQUARES}


def classify(image_rectified, calibration):
    """Return {square: {label, confidence, reasons, ...}} with label in empty/white/black/unknown."""
    raw, smooth = _prepare(image_rectified)
    empty_ref = [np.asarray(r) for r in calibration['emptyRef']]
    contrast = float(calibration['contrast'])
    white_ref = np.asarray(calibration['fillRef']['white'])
    black_ref = np.asarray(calibration['fillRef']['black'])
    tiles, raw_tiles = _tiles(smooth), _tiles(raw)
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
        return _abstain_all('frame-too-blurry')
    out = {}
    measures = [_measure(tiles[i] * gain + offset, empty_ref[DARK[i]], contrast) for i in range(64)]
    sharp = [_sharp_lighting(m['local']) for m in measures]
    for i in range(64):
        m = measures[i]
        saturated, sat_bad = _saturation(raw_tiles[i], m['local'])
        reasons = _local_reasons(m['local'])
        scores = {'border': _clamp(1 - m['border'] / (2 * BORDER_MAX_FRAC)),
                  'saturation': _clamp(1 - saturated / (2 * SATURATED_MAX_FRAC)) if sat_bad else 1.0}
        if m['border'] > BORDER_MAX_FRAC:
            reasons.append('background-mismatch')
        if sat_bad:
            reasons.append('saturated-pixels')
        if NEIGHBOUR_RULE:
            r, c = divmod(i, 8)
            if any(sharp[(r + dr) * 8 + c + dc] for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                   if (dr or dc) and 0 <= r + dr < 8 and 0 <= c + dc < 8):
                reasons.append('neighbour-lighting-not-smooth')
        fg_cue, edge_cue = _occupancy_cues(m)
        if fg_cue != edge_cue or fg_cue == 'ambiguous':
            reasons.append(f'occupancy-cues-disagree:{fg_cue}/{edge_cue}')
        if fg_cue == 'empty':
            scores['occupancy'] = _clamp(0.5 + 0.5 * (EMPTY_MAX_FG - m['fg']) / EMPTY_MAX_FG)
        elif fg_cue == 'piece':
            scores['occupancy'] = _clamp(0.5 + 0.5 * (m['fg'] - PIECE_MIN_FG) / PIECE_MIN_FG)
        else:
            scores['occupancy'] = 0.0
        label = 'empty' if fg_cue == 'empty' else 'piece'
        colour_info = {}
        if label == 'piece':
            if m['fill'] is None:
                reasons.append('no-fill-colour'); scores['colour'] = 0.0
            else:
                label, share, dist = _vote(m['fill'], white_ref, black_ref)
                colour_info = {'colourShare': round(share, 4), 'colourDist': round(dist, 2), 'fillPixels': len(m['fill'][0])}
                scores['colour'] = min(_clamp(0.5 + 0.5 * (share - COLOR_VOTE_MIN) / (1 - COLOR_VOTE_MIN)),
                                       _clamp(1 - dist / (2 * COLOR_MAX_DIST)))
                if share < COLOR_VOTE_MIN:
                    reasons.append('ambiguous-colour')
                if dist > COLOR_MAX_DIST:
                    reasons.append('unfamiliar-foreground-colour')
        if reasons:
            scores['gates'] = 0.0  # any fired gate means abstain, so confidence is below ABSTAIN_BELOW
        confidence = min(scores.values())
        cell = {'rawLabel': label, 'confidence': round(confidence, 4),
                'fgFrac': round(m['fg'], 4), 'edgeFrac': round(m['edge'], 4), 'borderFrac': round(m['border'], 4),
                'saturatedFrac': round(saturated, 4), 'local': {k: round(v, 3) for k, v in m['local'].items()}, **colour_info}
        if reasons or confidence < ABSTAIN_BELOW:
            cell.update(label='unknown', reasons=reasons or ['low-confidence'])
        else:
            cell.update(label=label, reasons=[])
        out[SQUARES[i]] = cell
    return out


def classify_image(image, calibration, shift=(0, 0)):
    """Marker corpus: rectify then classify; geometry failure -> all unknown."""
    try:
        panel = rectify(image)
    except ValueError as error:
        return _abstain_all(f'geometry:{error}'), False
    if shift != (0, 0):
        arr = np.roll(np.asarray(panel), shift=(shift[1], shift[0]), axis=(0, 1))
        panel = Image.fromarray(arr, 'RGB')
    return classify(panel, calibration), True


if __name__ == '__main__':
    print(json.dumps(policy(), indent=1))
