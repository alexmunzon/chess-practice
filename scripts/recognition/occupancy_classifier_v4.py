#!/usr/bin/env python3
"""Square reader v4: EMPTY / WHITE / BLACK / UNKNOWN per square (experiment, not app code).

A copy of v3.1 (occupancy_classifier_v3.py, frozen, sha256 c634a76d...926ee) with the smallest changes that
let it read other piece styles and last-move highlights (see docs/OCCUPANCY_CLASSIFIER_V4.md). Same public API:
calibrate(start_panel, occupancy), classify(panel, calibration), occupancy_from_fen, CalibrationError, policy(),
SQUARES, plus the marker-corpus helpers rectify / classify_image.

What changed versus v3.1 (V4 markers in the code):
  A. Bare-board mask learned from the start picture. v3 assumed pieces never reach the 3-8 px edge strips and
     ring of a square; solid site-style pieces do. At calibration every start piece's silhouette (all piece types,
     both colours, both square colours) is unioned, grown by MASK_GROW px, and only pixels outside that union are
     used for the lighting strips and the ring check (and for the clipped-ring test). With v3's own pieces the mask
     leaves v3's strips intact. If the learned mask leaves too few bare strip rows or ring pixels (noise, moire or
     lens bending counted as "piece"), v3's fixed geometry is used instead and the normal start checks decide.
  B. Colour-aware edge cue: the vertical-edge cue measures the RGB step, not the luminance step, and counts edges
     out to the strips. On a square colour where some start piece fails v3's edge scale (solid white on cream),
     the scale is the RGB gap from that square colour to the nearer piece fill (floor 0.5 x contrast), stored as
     edgeContrast; elsewhere v3's scale stays.
  C. Tinted squares (last-move highlights): a square whose whole bare ring has one uniform colour that the lighting
     model cannot explain may be read against that colour instead of the board colour, only if exactly two such
     squares form one consistent semi-transparent overlay pair, each tint is far from both piece colours and from
     the other square colour, and its neighbours are calm. Both occupancy cues must still agree, and EMPTY needs
     the window clear even at reduced thresholds (a piece faded by an overlay above it is not empty).
  D. Piece shape learned from the start: a piece reading must stand on the base row of the start pieces of its
     colour on that square colour, with a base about as wide, and cover about as much of the square. A piece
     drawn halfway between two squares, a piece of another style or a large occluder is unknown. The base row is
     the lowest row at least half as wide as the silhouette's widest row (stray noisy rows do not count).
  v4.1 (after an independent review): A's mask counts a pixel as covered only if two or more start squares cover
     it (a cursor or tooltip on one start piece is no longer learned). D: shape measured over the whole tile (pixels
     that are blends of the two board colours do not count), base row within 2 px, base centre within 3 px (also
     measured without the local lighting correction), no piece pixels below the base row, the base's white/black
     mix like the start pieces', and the piece's strongest contrast at least 0.6x the faintest start piece's (drag
     ghosts, pieces seen through a layer). F: see-through layers: an EMPTY square whose board colour has moved as far
     as a layer able to wash out a start piece would move it is unknown, and any square whose colour change needs a
     layer at least 50 % opaque is unknown (promotion chooser, dialogs).
  v4.2 (after a second review): G. EMPTY must hold under a see-through layer of ANY colour: the window must also be
     clear at a strict distance (16 RGB, or twice the start's empty-window noise), so only a layer opaque enough to
     squash the faintest piece below it could hide one; and the bare board, without any lighting correction, must not
     have moved beyond 3x the start's own largest empty-square move (at least 3 RGB). Any square whose bare board
     moved 40 RGB or more is unknown (replaces v4.1's 50 %-opacity bound). A piece is unknown if its silhouette
     holds clearly more opposite-colour pixels than the start pieces of its kind (a piece drawn over another), or
     its contrast is below 0.85x the faintest start piece's. The bare-board mask counts a pixel as piece area only
     if start pieces of both colours cover it.
  v4.3 (after a third review): G's bounds have fixed caps. The strict distance is always 16 RGB (start noise no
     longer raises it) and the move bound is 3x the start's largest empty-square move clamped to 3-6 RGB, so one
     glare spot on an empty start square can no longer switch G off for the game.
  E. EMPTY needs a visible piece to be possible: if local light (or a tint) has moved the square's own board
     colour so close to a piece fill that the gap is below EMPTY_FILL_KEEP x the start's gap, a solid piece of that
     colour could be invisible there, so the square is unknown. Last-move pairs (C) must also read as exactly one
     empty square and one piece (the square a piece left and the square it went to), else both are unknown.

v3.1 description, unchanged where not listed above:

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
import math
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
VERSION = 'v4.3'

# ---- Policy. Every threshold is here and returned by policy(). Development data only. ----
PRE_BLUR_RADIUS = 1.0         # Gaussian denoise before pixel tests (v2)
GAIN_RANGE = (0.33, 3.0)      # global light/dark correction allowed relative to calibration (v2: 0.5-2.0)
FRAME_SHARPNESS_MIN = 0.4     # square-boundary contrast vs calibration; below = whole frame unknown (v2)
CAL_SHARPNESS_MIN = 0.05      # v3.1: start's boundary sharpness must be finite and >= this, else the blur gate has no reference
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
# V4 A: bare-board mask learned from the start picture.
SIL_DISTANCE = 20.0           # start picture: RGB distance from the board colour that marks a piece pixel (half FG_DISTANCE)
MASK_GROW = 2                 # start piece silhouettes are grown by this many px (corner jitter, anti-aliasing)
STRIP_MIN_ROWS = 20           # rows (of 58) of each side strip that must stay bare, else the start is refused
RING_MIN_PIXELS = 40          # bare ring pixels (top/bottom rows) needed, else the start is refused
EDGE_CONTRAST_MIN = 0.5       # V4 B: the edge cue's per-square-colour step is never below this share of contrast
EMPTY_FILL_KEEP = 0.6         # V4 E: EMPTY needs each piece fill at least this share as far from the lit square as at the start
# V4 C: tinted squares (highlights). Shares are of the light/dark contrast unless stated.
TINT_MAX_ROW_DEV = 0.12       # each strip row / ring side may differ from the square's tint colour by at most this
TINT_MIN_FILL_DIST = 60.0     # RGB: tint colour at least this far from both piece fill colours (1.5 x FG_DISTANCE)
TINT_MIN_OTHER_DIST = 40.0    # RGB: tint colour at least this far from the other square colour (FG_DISTANCE)
TINT_PAIR_TOL = 0.25          # last-move highlights come as a pair with ONE overlay: same-colour squares' tints agree to this
TINT_MAX_ALPHA = 0.6          # pair on both square colours: overlay opacity implied by the two tints at most this
TINT_PAIR_RESIDUAL = 0.25     # ... and the two tints differ like the two board colours, up to this (share of contrast)
TINT_EMPTY_SCALE = 0.4        # a tinted square is EMPTY only if FG_DISTANCE and EDGE_LEVEL scaled by this also see nothing
# V4 D: a piece must look like the start pieces: standing on their common base, about their size.
BASE_MIN_RUN = 4              # silhouette row width (px) that counts as part of a piece
BASE_MIN_SHARE = 0.5          # ... and at least this share of the silhouette's widest row (the piece's base, not stray pixels)
BASE_ROW_TOL = 2              # v4.1 (was 4): piece's base row within this many px of the start pieces' common base row
BASE_COL_TOL = 3              # v4.1: centre of the piece's base within this many px of the start pieces' base centre
BASE_MIN_WIDTH = 0.75         # piece's base width at least this share of the narrowest start piece base
SIZE_RANGE = (0.6, 1.35)      # piece's foreground share within (low x smallest, high x largest) start piece
# v4.1 F: see-through layers (dialogs, banners, ghosts) over the board.
LAYER_COLOUR_MIN_DIST = 15.0  # RGB: layers at least this far from the board colour are covered; nearer (near board-coloured) ones are a limit
LAYER_MAX_MOVE = 40.0         # v4.2 (replaces v4.1's LAYER_MAX_OPACITY 0.5): any square whose bare board moved this far (RGB, = FG_DISTANCE) is unknown
PIECE_MIN_CONTRAST = 0.85     # v4.2 (was 0.6): a piece's strongest contrast (95th pct of its foreground distances) vs the faintest start piece of its kind
# v4.2 G: EMPTY must survive any see-through layer. Bounds come from the start picture's own empty squares.
EMPTY_STRICT_FG = 16.0        # RGB: an EMPTY window must also be clear at this distance (0.4 x FG_DISTANCE); v4.3: fixed,
                              # no longer raised by the start's empty-window noise
MOVE_NOISE_MARGIN = 3.0       # EMPTY needs the bare board's uncorrected move below this many times the start's largest
MOVE_MIN = 3.0                # ... empty-square move, and never demands less than this many RGB (a near-noiseless start)
MOVE_MAX = 6.0                # v4.3: ... and never allows more than this many RGB, whatever the start's noise
OPP_COLOUR_MARGIN = (0.03, 0.25)  # v4.2: a piece's share of opposite-colour pixels may exceed its kind's start maximum by
                                 # the larger of 0.03 and 0.25 x that maximum (classic pieces carry opposite-colour outlines)
BASE_COLOUR_ROWS = 6          # v4.1: the piece's lowest rows, whose white/black pixel mix must match the start pieces' ...
BASE_COLOUR_TOL = 0.3         # ... to within this share
MASK_MIN_SQUARES = 2          # v4.1 A: a pixel joins the bare-board mask's "covered" part only if >= this many start squares cover it

_T = TILE_SIZE
_BORDER = np.zeros((_T, _T), dtype=bool)
_BORDER[3:7, 3:-3] = True; _BORDER[-7:-3, 3:-3] = True
_BORDER[3:-3, 3:7] = True; _BORDER[3:-3, -7:-3] = True
_TOPBOT = np.zeros((_T, _T), dtype=bool)
_TOPBOT[3:7, 8:-8] = True; _TOPBOT[-7:-3, 8:-8] = True
_WINDOW = np.zeros((_T, _T), dtype=bool)
_WINDOW[8:58, 12:52] = True
_EDGE_WINDOW = np.zeros((_T, _T), dtype=bool)  # V4 B: edges counted out to the strips (solid pieces' sides lie there)
_EDGE_WINDOW[8:58, 8:56] = True
_SHAPE_BAND = np.zeros((_T, _T), dtype=bool)   # V4 D: where a standing piece's silhouette is measured
_SHAPE_BAND[3:, :] = True     # v4.1: down to the tile's last row and across its full width (was rows 8-60, cols 8-55)
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


def _sharpness_reference_ok(value):
    """v3.1: can value serve as the blur gate's reference? Only a finite number >= CAL_SHARPNESS_MIN can; with 0, a
    negative number, NaN or a missing value the gate 'sharpness < FRAME_SHARPNESS_MIN x reference' could never fire."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            and value >= CAL_SHARPNESS_MIN)


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


def _strip_rows(tile, cols, bare):
    """V4 A: per-row median of the BARE pixels of one side strip (rows 3..60); rows with no bare pixel take the
    value of the nearest row that has one. (v3: plain median of all strip pixels.)"""
    values = np.where(bare[_ROWS, cols][..., None], tile[_ROWS, cols], np.nan)
    has = bare[_ROWS, cols].any(axis=1)
    out = np.zeros((values.shape[0], 3))
    out[has] = np.nanmedian(values[has], axis=1)
    idx = np.flatnonzero(has)
    nearest = idx[np.abs(np.arange(values.shape[0])[:, None] - idx[None, :]).argmin(axis=1)]
    return out[nearest]


def _local_correction(tile, ref, contrast, bare):
    """Row-by-row board correction from the square's own left/right bare strips.

    Each smoothed strip row's difference from the board colour is fitted with a physical lighting model
    (_lighting_fit: banding = brightness factor, glare = added grey light). The offset applied to the square
    is the FITTED lighting, interpolated left to right, so anything the model cannot express (an occluder,
    a hand, a different colour) stays visible in the corrected tile and in 'unexplained'.
    V4 A: only strip pixels outside the start pieces' grown silhouettes are used.
    """
    left = _running_mean(_strip_rows(tile, _LEFT, bare) - ref, LOCAL_SMOOTH_ROWS)    # rows x 3
    right = _running_mean(_strip_rows(tile, _RIGHT, bare) - ref, LOCAL_SMOOTH_ROWS)
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
        'unexplained': float(max(res_l.max(), res_r.max())) / contrast}, (left, right)


def _edges(tile, contrast):
    """Horizontal colour steps (vertical edges) above EDGE_LEVEL x contrast.
    V4 B: the step is the RGB distance between the pixels either side (v3: luminance difference), so a boundary
    between colours of similar brightness (solid white piece on a cream square) still counts."""
    g = np.zeros(tile.shape[:2])
    g[:, 1:-1] = np.linalg.norm(tile[:, 2:] - tile[:, :-2], axis=2) / 2
    return g > EDGE_LEVEL * contrast


def _ring(bare):
    """V4 A: ring pixels checked against the board colour: v3's top/bottom ring where the start pieces leave it bare;
    if they cover it (solid pieces reaching the square's top and bottom), the whole bare edge band incl. the strips."""
    ring = _TOPBOT & bare
    return ring if ring.sum() >= RING_MIN_PIXELS else _BORDER & bare


def _measure_against(tile, corrected, ref, contrast, bare, local, empty_scale=1.0, edge_contrast=None, other_ref=None,
                     board_ref=None):
    """empty_scale < 1 (tinted squares, V4 C): the EMPTY cues also need the window clear at FG_DISTANCE and EDGE_LEVEL
    scaled by it, so a piece faded by an overlay drawn above it cannot pass as empty.
    edge_contrast (V4 B): the step the edge cue scales EDGE_LEVEL by on this square colour (default: contrast)."""
    edge_contrast = contrast if edge_contrast is None else edge_contrast
    dist = np.linalg.norm(corrected - ref, axis=2)
    fg = (dist > FG_DISTANCE) & _WINDOW
    fg_frac = float(fg.sum() / _WINDOW.sum())
    strict = {}
    if empty_scale < 1:
        strict['fgStrict'] = float(((dist > empty_scale * FG_DISTANCE) & _WINDOW).sum() / _WINDOW.sum())
        g = np.zeros(tile.shape[:2])
        g[:, 1:-1] = np.linalg.norm(tile[:, 2:] - tile[:, :-2], axis=2) / 2
        strict['edgeStrict'] = float(((g > empty_scale * EDGE_LEVEL * edge_contrast) & _EDGE_WINDOW).sum() / _WINDOW.sum())
    border_frac = float((dist[_ring(bare)] > FG_DISTANCE).mean())
    edges = _edges(tile, edge_contrast)
    edge_frac = float((edges & _EDGE_WINDOW).sum() / _WINDOW.sum())  # V4 B: same unit as v3 (share of _WINDOW)
    fill = None
    if fg.sum() >= MIN_FILL_PIXELS:
        weights = _deep_core(fg)
        if FILL_EDGE_GUARD >= 0:
            weights[_dilate(edges, FILL_EDGE_GUARD) if FILL_EDGE_GUARD else edges] = 0
        weights[COLOUR_MAX_ROW:] = 0
        core = weights > 0
        if core.sum() >= MIN_FILL_PIXELS:
            fill = (corrected[core], weights[core].astype(float))
    # V4 D shape. v4.1: measured over the whole tile below row 3; a pixel counts only if it is also far from every
    # blend of the two board colours, so the blurred boundary to a neighbouring square (and a neighbour's colour
    # shown by a corner error) is not taken for a piece.
    def piece_pixels(img):
        out = (np.linalg.norm(img - ref, axis=2) > FG_DISTANCE) & _SHAPE_BAND
        if other_ref is not None:
            span = other_ref - ref
            t = np.clip(((img - ref) @ span) / float(span @ span), 0.0, 1.0)
            out &= np.linalg.norm(img - ref - t[..., None] * span, axis=2) > FG_DISTANCE
        if board_ref is not None:  # tinted square: artwork parts drawn in the untinted square's colour do not count,
            out &= np.linalg.norm(img - board_ref, axis=2) > FG_DISTANCE  # as at the start
        return out
    piece = piece_pixels(corrected)
    # The width and centre of the base also use the square WITHOUT the local lighting correction: a piece pushed
    # sideways into the side strips is otherwise partly "corrected away" as lighting and looks centred.
    piece_raw = piece | piece_pixels(tile) if tile is not corrected else piece
    widths = piece.sum(axis=1)
    rows = np.flatnonzero(widths >= max(BASE_MIN_RUN, BASE_MIN_SHARE * widths.max()))  # stray noisy rows below a piece do not count
    if len(rows):
        r0 = int(rows[-1])
        wide = max(range(max(0, r0 - 3), r0 + 1), key=lambda r: widths[r])
        cols = np.flatnonzero(piece_raw[wide])
        below = bool((widths[r0 + BASE_ROW_TOL + 1:] >= BASE_MIN_RUN).any())  # piece pixels well below the base row
        base = (r0, int(len(cols)), float(cols[0] + cols[-1]) / 2, below)
        base_pix = corrected[max(0, r0 - BASE_COLOUR_ROWS + 1):r0 + 1][piece[max(0, r0 - BASE_COLOUR_ROWS + 1):r0 + 1]]
    else:
        base = (-1, 0, -1.0, False)
        base_pix = np.zeros((0, 3))
    fgd = dist[fg]
    return {'fg': fg_frac, 'border': border_frac, 'edge': edge_frac, 'fill': fill, 'local': local, 'base': base,
            'contrast95': float(np.percentile(fgd, 95)) if len(fgd) else 0.0, 'windowDist': dist[_WINDOW],
            'basePixels': base_pix, 'piecePixels': corrected[piece], **strict}


def _shape_reasons(m, shapes, label, dark, tinted=False):
    """V4 D: a piece read as `label` on a square of colour `dark` must stand on the base row of the start pieces of
    that colour on that square colour, with a base about as wide as theirs, and cover about as much of the square.
    A piece drawn halfway between squares, a piece of another style, or a large occluder fails one of these.
    On a tinted square the background differs from both board colours, so which outline parts show can differ:
    the piece may match the start pieces of its colour on either square colour."""
    kinds = [f'{label}-light', f'{label}-dark'] if tinted else [f"{label}-{'dark' if dark else 'light'}"]
    known = [shapes[k] for k in kinds if k in shapes]
    if not known:
        return ['no-start-piece-of-this-kind']
    row, width, centre, below = m['base']
    if below or not any(abs(row - s['baseRow']) <= BASE_ROW_TOL and abs(centre - s['baseCol']) <= BASE_COL_TOL
                        and width >= BASE_MIN_WIDTH * s['baseWidth'] for s in known):
        return ['piece-not-on-base']  # v4.1: also off-centre sideways, or piece pixels below the base row
    if not any(m['contrast95'] >= PIECE_MIN_CONTRAST * s['contrast95'] for s in known):
        return ['piece-fainter-than-start']  # v4.1 F: a faded drag ghost or a piece seen through a layer
    if not any(SIZE_RANGE[0] * s['fgMin'] <= m['fg'] <= SIZE_RANGE[1] * s['fgMax'] for s in known):
        return ['piece-size-unlike-start']
    return []


def _layer_opacity(delta, ref):
    """v4.1 F: the least opacity a see-through layer of ANY colour needs to move board colour `ref` by `delta` (rows x
    3): a layer of colour L and opacity a gives ref + a (L - ref) with L inside the RGB cube, so each channel needs
    a >= delta / (255 - ref) when it rises and a >= -delta / ref when it falls. Glare and banding cannot be told
    from such a layer in one square, so they get the same bound. Capped at 1."""
    up = delta / np.maximum(255.0 - ref, 1.0)
    down = -delta / np.maximum(ref, 1.0)
    return float(min(1.0, np.max(np.where(delta > 0, up, down))))


def _measure(tile, ref, contrast, bare, edge_contrast=None, other_ref=None):
    offset, local, strips = _local_correction(tile, ref, contrast, bare)
    m = _measure_against(tile, tile - offset, ref, contrast, bare, local, edge_contrast=edge_contrast,
                         other_ref=other_ref)
    m['strips'] = strips
    m['bg'] = ref + offset[_WINDOW].mean(axis=0)  # V4 E: the square's own lit board colour (fitted lighting included)
    rows = offset[8:58, 12:52].mean(axis=1)       # fitted lighting per window row
    m['layer'] = _layer_opacity(rows, ref)       # v4.1 F
    # v4.2 G: how far the square's bare board (side strips row by row and the ring), WITHOUT any lighting correction,
    # has moved from the board colour: the fitted lighting plus whatever the lighting model could not express.
    left, right = strips
    ring = tile[_ring(bare)] - ref
    m['move'] = float(np.linalg.norm(np.median(np.concatenate([left, right, ring]), axis=0)))
    return m


def _tint(tile, ref, contrast, bare, strips):
    """V4 C: if the square's whole bare ring (both side strips row by row, top and bottom rings) has one uniform
    colour offset from the board colour, return that tinted board colour, else None. Lighting is NOT also
    corrected on a tinted square: tint plus glare/banding stays unknown."""
    left, right = strips
    parts = [np.concatenate([left, right]) + ref]      # smoothed strip rows, absolute colour
    upper = np.arange(_T)[:, None] < _T // 2
    for half in (upper, ~upper):                        # top and bottom ring, where bare
        ring = tile[_ring(bare) & ~np.isin(np.arange(_T), np.r_[_LEFT, _RIGHT])[None, :] & half]
        if len(ring):
            parts.append(np.median(ring, axis=0)[None])
    values = np.concatenate(parts)
    colour = np.median(values, axis=0)
    dev = float(np.max(np.linalg.norm(values - colour, axis=1)))
    return colour if dev <= TINT_MAX_ROW_DEV * contrast else None


def _opposite_share(pixels, label, white_ref, black_ref):
    """v4.2: share of a piece's silhouette pixels nearer the OTHER colour's fill reference (0 if none)."""
    if not len(pixels):
        return 0.0
    near_white = np.linalg.norm(pixels - white_ref, axis=1) < np.linalg.norm(pixels - black_ref, axis=1)
    return float(np.mean(~near_white if label == 'white' else near_white))


def _empty_bounds(noise):
    """v4.2 G: (strict window distance, largest allowed bare-board move) for EMPTY, from the start's empty squares.
    v4.3: start noise can only tighten G, never loosen it past fixed caps. One glare spot on one empty start square
    made the noisiest-square statistics huge and switched G off for the whole game (third review). The strict distance
    is always EMPTY_STRICT_FG; the move bound is clamped to [MOVE_MIN, MOVE_MAX]. A noisier start is still accepted:
    its later empty squares that move beyond the cap are unknown, never read with a looser bound."""
    return EMPTY_STRICT_FG, min(MOVE_MAX, max(MOVE_MIN, MOVE_NOISE_MARGIN * noise['move']))


def _white_share(pixels, white_ref, black_ref):
    """v4.1: where the pixels sit, on average, between the black (0) and white (1) fill references (0.5 if none)."""
    if not len(pixels):
        return 0.5
    span = white_ref - black_ref
    return float(np.mean(np.clip((pixels - black_ref) @ span / float(span @ span), 0.0, 1.0)))


def _vote(fill, white_ref, black_ref):
    """Depth-weighted vote of core pixels for the nearer fill reference (v2 rule, v3 references)."""
    fill, weights = fill
    d_w = np.linalg.norm(fill - white_ref, axis=1)
    d_b = np.linalg.norm(fill - black_ref, axis=1)
    white_share = float(weights[d_w < d_b].sum() / weights.sum())
    label = 'white' if white_share >= 0.5 else 'black'
    return label, max(white_share, 1 - white_share), float(np.median(np.minimum(d_w, d_b)))


def _occupancy_cues(m):
    if m['fg'] <= EMPTY_MAX_FG and m.get('fgStrict', 0.0) <= EMPTY_MAX_FG:
        fg_cue = 'empty'
    elif m['fg'] >= PIECE_MIN_FG:
        fg_cue = 'piece'
    else:
        fg_cue = 'ambiguous'
    if m['edge'] <= EMPTY_MAX_EDGE and m.get('edgeStrict', 0.0) <= EMPTY_MAX_EDGE:
        edge_cue = 'empty'
    elif m['edge'] >= PIECE_MIN_EDGE:
        edge_cue = 'piece'
    else:
        edge_cue = 'ambiguous'
    return fg_cue, edge_cue


def _saturation(raw_tile, local, bare):
    """(clipped share of the square, True if that clipping forces abstention). Clipping inside the window of a
    square whose ring is unclipped and whose local lighting is calm is a bright white piece (allowed); clipping
    on the ring, or under a glare/stripe, can hide what is there (abstain).
    V4 A: the ring is the BARE part of v3's edge band (solid pieces reach into the band and may clip there)."""
    clipped = raw_tile.min(axis=2) >= SATURATED_LEVEL
    frac = float(clipped.mean())
    if frac <= SATURATED_MAX_FRAC:
        return frac, False
    calm = local['shift'] <= SATURATED_OK_MAX_SHIFT and float(clipped[_BORDER & bare].mean()) <= SATURATED_OK_MAX_RING
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


def _bare_mask(tiles, occ, empty_ref):
    """V4 A: tile pixels that no start piece covers: pixels that differ from their square's board colour by more than
    SIL_DISTANCE on at least MASK_MIN_SQUARES occupied start squares, grown by MASK_GROW px; the rest is bare board.
    v4.1: a single square (a cursor or tooltip over one start piece) no longer enters the mask; every piece shape of
    a full start set appears on two or more squares, so real pieces still do."""
    count = {'white': np.zeros((_T, _T), dtype=int), 'black': np.zeros((_T, _T), dtype=int)}
    for i in range(64):
        if occ[i] != 'empty':
            count[occ[i]] += np.linalg.norm(tiles[i] - empty_ref[DARK[i]], axis=2) > SIL_DISTANCE
    # v4.2: and on squares of BOTH piece colours (a start shows each artwork shape in both colours), so a box or
    # banner across one side's pieces (rank 2 or rank 7) is not learned as piece area.
    covered = (count['white'] + count['black'] >= MASK_MIN_SQUARES) & (count['white'] >= 1) & (count['black'] >= 1)
    return ~_dilate(covered, MASK_GROW)


def _layer_hide(window_dists):
    """v4.1 F: the least opacity of a see-through layer that could make some start piece of a kind fall below
    PIECE_MIN_FG foreground. A layer of opacity a shrinks every colour difference under it by (1 - a), so a piece
    pixel stays foreground only if its distance d > FG_DISTANCE / (1 - a). 1.0 if no opacity below 1 hides it."""
    for a in np.arange(0.0, 1.0, 0.01):
        if min(float(np.mean(d > FG_DISTANCE / (1.0 - a))) for d in window_dists) < PIECE_MIN_FG:
            return round(float(a), 2)
    return 1.0


def _mask_problem(bare):
    """Why a bare mask cannot serve (too few bare strip rows or ring pixels), or None."""
    for name, cols in (('left', _LEFT), ('right', _RIGHT)):
        if int(bare[_ROWS, cols].any(axis=1).sum()) < STRIP_MIN_ROWS:
            return f'start-pieces-cover-{name}-strips'
    if int(_ring(bare).sum()) < RING_MIN_PIXELS:
        return 'start-pieces-cover-ring'
    return None


def _mask_from_calibration(calibration):
    try:
        rows = calibration['bareMask']
        bare = np.array([[ch == '1' for ch in row] for row in rows], dtype=bool)
        if bare.shape != (_T, _T) or any(set(row) - {'0', '1'} for row in rows):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return None if _mask_problem(bare) else bare


def _shape_from_calibration(calibration):
    """V4 D: the learned piece shapes {'white-light': {...}, ...}; None if missing or malformed. A kind (colour on
    square colour) absent from the start is simply missing, and such pieces are unknown later."""
    shapes = calibration.get('pieceShape')
    keys = ('baseRow', 'baseWidth', 'baseCol', 'fgMin', 'fgMax', 'contrast95', 'layerHide', 'baseWhite', 'oppMax')
    if not isinstance(shapes, dict) or not shapes:
        return None
    for shape in shapes.values():
        if not isinstance(shape, dict) or not all(isinstance(shape.get(k), (int, float)) and not isinstance(shape.get(k), bool)
                                                  and math.isfinite(shape[k]) for k in keys):
            return None
        if (shape['baseWidth'] < BASE_MIN_RUN or not 0 < shape['fgMin'] <= shape['fgMax'] or shape['contrast95'] <= 0
                or not 0 <= shape['layerHide'] <= 1):
            return None
    return shapes


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
    bare = _bare_mask(tiles, occ, empty_ref)
    if _mask_problem(bare):
        # V4 A: the start pieces (or noise, moire, lens bending that differs from the board colour) leave too few bare
        # strip rows or ring pixels for a learned mask. Fall back to v3's fixed geometry (every strip and ring pixel
        # is board); the checks below then refuse the start if pieces really do reach the strips or ring.
        bare = np.ones((_T, _T), dtype=bool)
    measures = [_measure(tiles[i], empty_ref[DARK[i]], contrast, bare) for i in range(64)]
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
    # V4 B: a solid piece whose fill is closer to its square's colour than the light/dark contrast (white on cream)
    # shows a smaller step at its outline. Only on a square colour where some start piece fails v3's edge cue, the
    # cue is scaled by that step instead (RGB distance from the square colour to the nearer piece fill, never below
    # EDGE_CONTRAST_MIN x contrast); elsewhere v3's scale stays. The fills do not depend on the edge cue.
    reduced = _edge_contrast(empty_ref, white_ref, black_ref, contrast)
    edge_contrast = [contrast, contrast]
    for parity in (0, 1):
        if any(occ[i] != 'empty' and DARK[i] == parity and _occupancy_cues(measures[i])[1] != 'piece' for i in range(64)):
            edge_contrast[parity] = reduced[parity]
    measures = [_measure(tiles[i], empty_ref[DARK[i]], contrast, bare, edge_contrast[DARK[i]], empty_ref[1 - DARK[i]])
                for i in range(64)]
    for i, m in enumerate(measures):
        reasons = _local_reasons(m['local'])
        if _saturation(raw_tiles[i], m['local'], bare)[1]:
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
    shape = {}
    for colour in ('white', 'black'):
        for parity, name in ((0, 'light'), (1, 'dark')):
            idx = [i for i in range(64) if occ[i] == colour and DARK[i] == parity]
            if len(idx) < MIN_SAMPLES_PER_CLASS:
                continue  # no reference for this kind: such pieces will be unknown in later pictures
            row = int(np.median([measures[i]['base'][0] for i in idx]))
            on = [i for i in idx if abs(measures[i]['base'][0] - row) <= BASE_ROW_TOL]
            if 2 * len(on) <= len(idx):  # most start pieces do not share a base row: no standing-piece reference (V4 D)
                problems.append((SQUARES[next(i for i in idx if i not in on)], 'start-pieces-not-on-a-common-base'))
                continue
            # A minority off the common base row (a noisy start square) does not set the base width.
            shape[f'{colour}-{name}'] = {'baseRow': row, 'baseWidth': int(min(measures[i]['base'][1] for i in on)),
                                         'baseCol': float(np.median([measures[i]['base'][2] for i in on])),
                                         'fgMin': float(min(measures[i]['fg'] for i in idx)),
                                         'fgMax': float(max(measures[i]['fg'] for i in idx)),
                                         'contrast95': float(min(measures[i]['contrast95'] for i in idx)),
                                         'layerHide': _layer_hide([measures[i]['windowDist'] for i in idx]),
                                         'oppMax': float(max(_opposite_share(measures[i]['piecePixels'], colour, white_ref,
                                                                             black_ref) for i in idx)),
                                         'baseWhite': float(np.median([_white_share(measures[i]['basePixels'], white_ref,
                                                                                    black_ref) for i in on]))}
    for colour, values in shares.items():
        if np.mean(values) < CAL_VOTE_MEAN_MIN:
            problems.append(('*', f'{colour}-pieces-colour-vote-weak'))
    if problems:
        raise CalibrationError(f'{len(problems)} square(s) disagree with stated occupancy: '
                               + ', '.join(f'{s}:{r}' for s, r in problems[:8]))
    # v4.2 G: the start's own empty squares say how still a bare board is in this picture (noise, JPEG, moire).
    empties = [i for i in range(64) if occ[i] == 'empty']
    empty_noise = {'move': float(max(measures[i]['move'] for i in empties)),
                   'window': float(np.percentile(np.concatenate([measures[i]['windowDist'] for i in empties]), 99))}
    sharpness = _sharpness(smooth)
    if not _sharpness_reference_ok(sharpness):  # v3.1: no usable reference for the blur gate -> not a start picture
        raise CalibrationError(f'start-boundary-sharpness-unusable:{sharpness!r}')
    return {'version': VERSION, 'emptyRef': [r.tolist() for r in empty_ref], 'contrast': contrast,
            'boundarySharpness': sharpness, 'fillRef': {'white': white_ref.tolist(),
                                                                'black': black_ref.tolist()},
            'bareMask': [''.join('1' if v else '0' for v in row) for row in bare], 'pieceShape': shape,
            'edgeContrast': edge_contrast, 'emptyNoise': empty_noise,
            'policy': policy()}


# ---------------------------------------------------------- classification ----
def _edge_contrast(empty_ref, white_ref, black_ref, contrast):
    """V4 B: per square colour (light, dark), the edge cue's reference step: the light/dark contrast, or the RGB
    distance from that square colour to the nearer piece fill when smaller, floored at EDGE_CONTRAST_MIN x contrast."""
    return [float(max(EDGE_CONTRAST_MIN * contrast, min(contrast, np.linalg.norm(white_ref - ref),
                                                         np.linalg.norm(black_ref - ref)))) for ref in empty_ref]


def _tinted_squares(corrected, measures, empty_ref, white_ref, black_ref, contrast, bare):
    """V4 C: squares to read against their own tint colour, {index: colour}, and refusal reasons {index: [reason]}.
    Candidates are squares the lighting model could not explain whose whole bare ring is one uniform colour. They
    are read as tinted only if they form ONE last-move pair painted with one overlay: exactly two candidates; on
    the same square colour their tints agree; on different square colours the two tints differ like the two board
    colours scaled by (1 - opacity) with opacity <= TINT_MAX_ALPHA (an opaque box looks the same on both colours).
    Each tint must also be far from both piece fill colours and from the other square colour, and every neighbour
    must be calm or the other candidate, so an occluder that spills onto a neighbour is refused."""
    disturbed = [bool(_local_reasons(m['local'])) or m['border'] > BORDER_MAX_FRAC for m in measures]
    candidates = {}
    for i in range(64):
        if disturbed[i]:
            colour = _tint(corrected[i], empty_ref[DARK[i]], contrast, bare, measures[i]['strips'])
            if colour is not None:
                candidates[i] = colour
    if len(candidates) != 2:
        return {}, {i: ['tinted-squares-not-one-pair'] for i in candidates}
    (i, ci), (j, cj) = candidates.items()
    if DARK[i] == DARK[j]:
        pair_ok = np.linalg.norm(ci - cj) <= TINT_PAIR_TOL * contrast
    else:
        if DARK[i]:
            ci, cj = cj, ci  # ci on the light square
        board = empty_ref[0] - empty_ref[1]
        k = float((ci - cj) @ board / (board @ board))  # (1 - opacity)
        pair_ok = (1 - TINT_MAX_ALPHA <= k <= 1.0 + TINT_PAIR_RESIDUAL
                   and np.linalg.norm(ci - cj - k * board) <= TINT_PAIR_RESIDUAL * contrast)
    if not pair_ok:
        return {}, {i: ['tinted-pair-inconsistent'] for i in candidates}
    accepted, reasons = {}, {}
    for i, colour in candidates.items():
        r, c = divmod(i, 8)
        neighbours = [(r + dr) * 8 + c + dc for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                      if (dr or dc) and 0 <= r + dr < 8 and 0 <= c + dc < 8]
        if min(np.linalg.norm(colour - white_ref), np.linalg.norm(colour - black_ref)) < TINT_MIN_FILL_DIST:
            reasons[i] = ['tint-close-to-piece-colour']
        elif np.linalg.norm(colour - empty_ref[1 - DARK[i]]) < TINT_MIN_OTHER_DIST:
            reasons[i] = ['tint-close-to-other-square-colour']
        elif any(disturbed[j] and j not in candidates for j in neighbours):
            reasons[i] = ['tint-neighbour-not-calm']
        else:
            accepted[i] = colour
    return accepted, reasons



def _abstain_all(reason):
    return {s: {'label': 'unknown', 'confidence': 0.0, 'reasons': [reason]} for s in SQUARES}


def classify(image_rectified, calibration):
    """Return {square: {label, confidence, reasons, ...}} with label in empty/white/black/unknown."""
    if not _sharpness_reference_ok(calibration.get('boundarySharpness')):  # v3.1: blur gate would be switched off
        return _abstain_all('calibration-sharpness-invalid')
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
    bare = _mask_from_calibration(calibration)
    if bare is None:  # V4 A: no usable bare-board mask, so no lighting strips to trust
        return _abstain_all('calibration-mask-invalid')
    shape = _shape_from_calibration(calibration)
    if shape is None:  # V4 D: no learned piece shape, so no check that a piece stands where it should
        return _abstain_all('calibration-shape-invalid')
    edge_contrast = calibration.get('edgeContrast')
    if not (isinstance(edge_contrast, list) and len(edge_contrast) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                    and EDGE_CONTRAST_MIN * contrast - 1e-9 <= v <= contrast + 1e-9 for v in edge_contrast)):
        return _abstain_all('calibration-edge-contrast-invalid')  # V4 B: the edge cue would have no valid scale
    noise = calibration.get('emptyNoise')
    if not (isinstance(noise, dict) and all(isinstance(noise.get(k), (int, float)) and not isinstance(noise.get(k), bool)
                                            and math.isfinite(noise[k]) and noise[k] >= 0 for k in ('move', 'window'))):
        return _abstain_all('calibration-empty-noise-invalid')  # v4.2 G: no bound for proving a square empty
    strict_fg, max_move = _empty_bounds(noise)
    out = {}
    corrected = [tiles[i] * gain + offset for i in range(64)]
    measures = [_measure(corrected[i], empty_ref[DARK[i]], contrast, bare, edge_contrast[DARK[i]], empty_ref[1 - DARK[i]])
                for i in range(64)]
    sharp = [_sharp_lighting(m['local']) for m in measures]
    tinted, tint_reasons = _tinted_squares(corrected, measures, empty_ref, white_ref, black_ref, contrast, bare)
    for i, colour in tinted.items():  # V4 C: read a tinted square against its own uniform tint colour
        calm = {'shift': 0.0, 'step': 0.0, 'side': 0.0, 'unexplained': 0.0}
        measures[i] = _measure_against(corrected[i], corrected[i], colour, contrast, bare, calm, TINT_EMPTY_SCALE,
                                       edge_contrast[DARK[i]], empty_ref[1 - DARK[i]], empty_ref[DARK[i]])
        measures[i]['bg'] = colour
        measures[i]['layer'] = 0.0  # a tint is read as drawn under the pieces; V4 C's own rules guard it
    # v4.1 F: per square colour, the least layer opacity that could hide some start piece of either colour there
    hide = []
    for name in ('light', 'dark'):
        here = [shape[f'{c}-{name}']['layerHide'] for c in ('white', 'black') if f'{c}-{name}' in shape]
        hide.append(min(here) if len(here) == 2 else min(v['layerHide'] for v in shape.values()))
    # V4 E: how far each piece fill was from each square colour at the start (what makes a piece visible there)
    fill_gap = [[float(np.linalg.norm(ref_c - empty_ref[p])) for ref_c in (white_ref, black_ref)] for p in (0, 1)]
    for i in range(64):
        m = measures[i]
        saturated, sat_bad = _saturation(raw_tiles[i], m['local'], bare)
        reasons = _local_reasons(m['local']) + tint_reasons.get(i, [])
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
        if label == 'empty':
            # V4 E: 'nothing differs from the board' only means empty if a piece WOULD differ. Where local light (or a
            # tint the lighting model absorbed) has pulled the board colour toward a piece fill, a solid piece of
            # that colour could be invisible, so the square is unknown.
            gaps = [float(np.linalg.norm(ref_c - m['bg'])) for ref_c in (white_ref, black_ref)]
            if any(g < EMPTY_FILL_KEEP * g0 for g, g0 in zip(gaps, fill_gap[DARK[i]])):
                reasons.append('background-near-piece-colour')
            # v4.1 F: the square's colour change could be a see-through layer opaque enough to wash a start piece
            # below the foreground level (hide = that opacity, learned per square colour). Opacity a of colour L
            # moves the board by a |L - board|; the least opacity any layer needs for the observed move is checked
            # first, then layers at least LAYER_COLOUR_MIN_DIST from the board colour: a move of hide x that
            # distance or more could be such a layer. (A layer closer to the board colour than that, or an opaque
            # board-coloured box, looks like an empty square: a limit.)
            # Not on tinted squares (V4 C): a highlight is drawn under the pieces and its strict EMPTY window
            # (TINT_EMPTY_SCALE) and pair rules guard it instead.
            if i not in tinted and (m['layer'] >= hide[DARK[i]] or np.linalg.norm(m['bg'] - empty_ref[DARK[i]])
                                    >= hide[DARK[i]] * LAYER_COLOUR_MIN_DIST):
                reasons.append('piece-could-be-under-a-layer')
            # v4.2 G: a see-through layer of ANY colour squashes a piece under it by (1 - a) and moves the bare board
            # by a x (its distance from the board colour). EMPTY is claimed only if (1) the window is clear even at
            # the strict distance, so only a layer opaque enough to squash the faintest piece below it could hide one,
            # and (2) the bare board, uncorrected, has not moved beyond the start's own noise (v4.3: never more than
            # MOVE_MAX RGB), so such a layer would have to be (nearly) the board's own colour, which no reader can see
            # in one picture.
            if i not in tinted and (m['move'] >= max_move or np.mean(m['windowDist'] > strict_fg) > EMPTY_MAX_FG):
                reasons.append('empty-not-provable-under-a-layer')
        # v4.1 F, v4.2: a bare board moved by FG_DISTANCE or more (uncorrected) may be a layer (a promotion chooser,
        # a dialog) with whatever shows drawn on top of it. v4.1 bounded the layer's opacity instead; that bound is
        # inflated on light squares with little headroom and cost reads on undisturbed pictures.
        if i not in tinted and m['move'] >= LAYER_MAX_MOVE:
            reasons.append('possible-see-through-layer')
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
                reasons += _shape_reasons(m, shape, label, DARK[i], i in tinted)
                # v4.2: both piece colours clearly inside one silhouette (a piece drawn over another piece). Not on
                # tinted squares: there the artwork's board-coloured parts blend with the tint (a limit).
                kinds_here = [f"{label}-{'dark' if DARK[i] else 'light'}"]
                opp = _opposite_share(m['piecePixels'], label, white_ref, black_ref)
                if i not in tinted and not any(k in shape and opp <= shape[k]['oppMax'] + max(OPP_COLOUR_MARGIN[0], OPP_COLOUR_MARGIN[1]
                                                                          * shape[k]['oppMax']) for k in kinds_here):
                    reasons.append('two-piece-colours-in-one-silhouette')
                # v4.1: the piece's base must have the colour mix of the start pieces' bases of its kind; a piece held
                # above another piece (drag, capture animation) shows the lower piece's base under its own body.
                kinds = [f'{label}-light', f'{label}-dark'] if i in tinted else [f"{label}-{'dark' if DARK[i] else 'light'}"]
                share = _white_share(m['basePixels'], white_ref, black_ref)
                if not any(k in shape and abs(share - shape[k]['baseWhite']) <= BASE_COLOUR_TOL for k in kinds):
                    reasons.append('piece-base-unlike-start')
        if reasons:
            scores['gates'] = 0.0  # any fired gate means abstain, so confidence is below ABSTAIN_BELOW
        confidence = min(scores.values())
        if i in tinted:
            colour_info['tint'] = [round(float(v), 1) for v in tinted[i]]
        cell = {'rawLabel': label, 'confidence': round(confidence, 4),
                'fgFrac': round(m['fg'], 4), 'edgeFrac': round(m['edge'], 4), 'borderFrac': round(m['border'], 4),
                'saturatedFrac': round(saturated, 4), 'local': {k: round(v, 3) for k, v in m['local'].items()}, **colour_info}
        if reasons or confidence < ABSTAIN_BELOW:
            cell.update(label='unknown', reasons=reasons or ['low-confidence'])
        else:
            cell.update(label=label, reasons=[])
        out[SQUARES[i]] = cell
    # V4 C: a last-move highlight marks the square a piece left (now empty) and the square it went to (now occupied).
    # Two tinted squares that do not read as exactly one empty and one piece are not that, e.g. opaque boxes hiding
    # whatever is under them read as two empty squares: both are unknown.
    if tinted:
        names = [SQUARES[i] for i in tinted]
        got = sorted('empty' if out[n]['label'] == 'empty' else 'piece' if out[n]['label'] in ('white', 'black')
                     else 'unknown' for n in names)
        if got != ['empty', 'piece']:
            for n in names:
                out[n].update(label='unknown', confidence=0.0, reasons=out[n]['reasons'] + ['tinted-pair-not-one-move'])
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
