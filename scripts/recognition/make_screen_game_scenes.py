#!/usr/bin/env python3
"""Seeded SIMULATED head-camera frames of whole chess games shown on a screen, with an answer key.

Experiment-only. Every image is synthetic: one fixed 2D piece artwork (scripts/simulation/appearance.py)
on a flat screen canvas, projected into a 1920x1080 room by a known homography, then degraded.
Reuses make_screen_scenes.py (canvas, room, keyboard, hand, homography helpers) without editing it.

Per game: one screen layout, one room and one base camera; the board content changes with each
legal move (lines from make-game-lines.mjs / chess.js). Camera modes: fixed (identical homography),
jitter (head tremor, <1.5% of board width), drift (slow cumulative change, up to ~15% of board width).
Photometric noise is fresh every frame; glare / hand / banding appear on a minority of medium/hard
frames and never as glare/hand on frame 0. Truth: <out>/truth/games.json (schema screen-game-truth-v1).

Pixel convention: pixel (i, j) has its centre at continuous coordinate (i, j).
"""
import argparse
import io
import json
import math
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'simulation'))
import make_screen_scenes as mss  # noqa: E402
from make_screen_scenes import (BOARD, DIFFICULTY, FOCAL, FRAME_H, FRAME_W, apply_h, bilinear,  # noqa: E402
                                draw_keyboard, hand, make_canvas, room)
from appearance import DARK_TILE, LIGHT_TILE, render_tile  # noqa: E402
from PIL import ImageFont  # noqa: E402
from render import labels_from_fen  # noqa: E402

REPO = HERE.parents[1]
LINES_SCRIPT = HERE / 'make-game-lines.mjs'
TILE = BOARD // 8
MODES = ('fixed', 'jitter', 'drift')
# Per-frame disturbance probabilities (medium/hard only; never glare/hand on frame 0).
DISTURB = {'easy': dict(glare=0.0, hand=0.0, banding=0.0),
           'medium': dict(glare=0.18, hand=0.12, banding=0.18),
           'hard': dict(glare=0.28, hand=0.2, banding=0.28)}

# Scripted openings that force the special moves (checked by chess.js); random legal play continues.
SPECIAL_GAME = ['e4', 'Nf6', 'e5', 'd5', 'exd6', 'Bf5', 'dxc7', 'Nbd7', 'cxd8=Q+', 'Rxd8', 'd4', 'e6', 'Nc3',
                'Be7', 'Be3', 'O-O', 'Qd2', 'Nb6', 'O-O-O', 'Nbd5', 'Nxd5', 'Nxd5', 'Bd3', 'Bxd3', 'Qxd3']
SCRIPTS = {
    'dev': [
        dict(prefix=SPECIAL_GAME),  # en passant, queen promotion, O-O, O-O-O
        dict(prefix=['e4', 'Nf6', 'e5', 'd5', 'exd6', 'Bf5', 'dxc7', 'Nbd7', 'cxd8=N']),  # ep + knight under-promotion
        dict(prefix=['e4', 'e5', 'Nf3', 'Nc6', 'Bc4', 'Bc5', 'O-O', 'Nf6', 'd3', 'O-O']),  # two O-O
        dict(prefix=['d4', 'd5', 'c4', 'dxc4', 'Nc3', 'Nc6', 'Bf4', 'Bf5', 'Qd2', 'Qd7', 'O-O-O', 'O-O-O']),
        dict(hidden=['e4', 'e5', 'Nf3', 'Nc6', 'Bb5', 'a6', 'Ba4', 'Nf6', 'O-O', 'Be7', 'Re1', 'b5', 'Bb3', 'd6']),
    ],
    'heldout': [
        dict(prefix=['d4', 'Nf6', 'd5', 'e5', 'dxe6', 'Bc5', 'exf7+', 'Ke7', 'f8=R']),  # ep + rook under-promotion
        dict(prefix=['h4', 'g5', 'hxg5', 'h6', 'gxh6', 'Bg7', 'hxg7', 'Nf6', 'gxh8=Q+']),  # queen promotion
        dict(prefix=['c4', 'e5', 'Nc3', 'Nf6', 'g3', 'Bb4', 'Bg2', 'O-O', 'Nf3', 'Re8', 'O-O']),  # two O-O
        dict(prefix=['e4', 'c5', 'Nf3', 'd6', 'd4', 'cxd4', 'Nxd4', 'Nf6', 'Nc3', 'a6', 'Be3', 'e5', 'Nb3', 'Be6',
                     'f3', 'Be7', 'Qd2', 'O-O', 'O-O-O']),  # O-O and O-O-O
        dict(hidden=['e4', 'c5', 'Nf3', 'd6', 'd4', 'cxd4', 'Nxd4', 'Nf6', 'Nc3', 'g6', 'Be2', 'Bg7', 'O-O', 'Nc6']),
    ],
    # Round two (repeated pictures per position): new openings, distinct from dev/heldout.
    'dev2': [
        dict(prefix=['e4', 'd5', 'e5', 'f5', 'exf6', 'Nc6', 'fxg7', 'Bd7', 'gxh8=Q']),  # ep + queen promotion
        dict(prefix=['a4', 'b5', 'axb5', 'a6', 'bxa6', 'Bb7', 'axb7', 'Nc6', 'bxa8=B']),  # bishop under-promotion
        dict(prefix=['Nf3', 'Nf6', 'g3', 'g6', 'Bg2', 'Bg7', 'O-O', 'O-O']),  # two O-O
        dict(prefix=['e4', 'e5', 'd4', 'exd4', 'Qxd4', 'Nc6', 'Qe3', 'd6', 'Nc3', 'Be6', 'Bd2', 'Qd7',
                     'O-O-O', 'O-O-O']),  # two O-O-O
        dict(hidden=['e4', 'e6', 'd4', 'd5', 'Nc3', 'Bb4', 'e5', 'c5', 'a3', 'Bxc3+', 'bxc3', 'Ne7', 'Qg4', 'O-O']),
    ],
    'heldout2': [
        dict(prefix=['g4', 'h5', 'g5', 'f5', 'gxf6', 'Nh6', 'fxg7', 'e6', 'gxh8=R']),  # ep + rook under-promotion
        dict(prefix=['b4', 'a5', 'bxa5', 'b6', 'axb6', 'Ba6', 'bxc7', 'Nc6', 'cxd8=Q+']),  # queen promotion
        dict(prefix=['e4', 'c6', 'd4', 'd5', 'Nc3', 'dxe4', 'Nxe4', 'Nf6', 'Nxf6+', 'exf6', 'Bc4', 'Bd6', 'Nf3',
                     'O-O', 'O-O']),  # two O-O
        dict(prefix=['d4', 'Nf6', 'c4', 'e6', 'Nc3', 'Bb4', 'Bg5', 'h6', 'Bh4', 'O-O', 'Qc2', 'b6', 'e3', 'Bb7',
                     'O-O-O']),  # O-O and O-O-O
        dict(hidden=['d4', 'd5', 'c4', 'e6', 'Nc3', 'Nf6', 'Bg5', 'Be7', 'e3', 'O-O', 'Nf3', 'h6', 'Bh4', 'b6']),
    ],
}
SEED0 = {'smoke': 900, 'dev': 1000, 'heldout': 2000, 'smoke2': 3900, 'dev2': 3000, 'heldout2': 4000,
         'stressdev': 5000, 'stressheld': 6000}
STICKY_P = 0.3  # share of disturbed positions whose glare/hand stays put for all pictures of the position
# Slot order inside a split (scripted lines spread over difficulties / modes).
SCRIPT_SLOT = {0: 0, 4: 1, 8: 2, 1: 3, 6: 4}


def game_plan(split, n_games, seed0, per_position=None):
    """per_position=None: legacy layout (each position once, ~10% random repeats).
    per_position=N: every position shown 1+N times in a row (games of 25-35 positions)."""
    base = split.rstrip('0123456789')
    plan = []
    for i in range(n_games):
        seed = seed0 + i
        r = np.random.default_rng([seed, 7])
        if base == 'smoke':
            difficulty, mode, white_bottom, plies, reps = 'easy', 'fixed', i == 0, 7, 0
        else:
            difficulty = ('easy', 'medium', 'hard')[i % 3]
            mode = MODES[(i + i // 3) % 3]
            white_bottom = i not in (1, 5, 8, 10)
            if per_position is None:
                plies = int(r.integers(27, 38))
                reps = int(round(plies * 0.1))
            else:
                plies, reps = int(r.integers(24, 35)), 0  # 25-35 positions including the start
        script = SCRIPTS.get(split, [])[SCRIPT_SLOT[i]] if base != 'smoke' and i in SCRIPT_SLOT else {}
        plies = max(plies, len(script.get('prefix', [])) + 4) if script.get('prefix') else plies
        entry = dict(id=f'{split}-g{i:02d}', split=split, seed=seed, difficulty=difficulty, cameraMode=mode,
                     whiteAtBottom=white_bottom, plies=plies, repeats=reps,
                     prefix=script.get('prefix', []), hidden=script.get('hidden', []))
        if per_position is not None:
            entry['perPosition'] = per_position
        plan.append(entry)
    return plan


def stress_plan(split, seed0, variants):
    """3 games per variant: easy photometrics, jitter camera, 12-15 positions, 3 pictures per position.
    'baseline' reuses the seeds (so the camera, room, noise and move line) of 'style-unfamiliar'."""
    plan = []
    for name in variants:
        vi = STRESS_VARIANTS.index('style-unfamiliar' if name == 'baseline' else name)
        for k in range(3):
            seed = seed0 + vi * 10 + k
            r = np.random.default_rng([seed, 7])
            level = STRESS_LEVELS[name][k] if name in STRESS_LEVELS else None
            plan.append(dict(id=f'{split}-{name}-g{k}', split=split, seed=seed, difficulty='easy', cameraMode='jitter',
                             whiteAtBottom=k != 1, plies=int(r.integers(11, 15)), repeats=0, prefix=[], hidden=[],
                             perPosition=2, stress=dict(name=name, level=level)))
    return plan


def game_lines(plan):
    req = {'games': [dict(id=g['id'], seed=g['seed'], prefix=g['prefix'], hiddenPrefix=g['hidden'],
                          plies=g['plies']) for g in plan]}
    run = subprocess.run(['node', str(LINES_SCRIPT)], input=json.dumps(req), capture_output=True, text=True,
                         cwd=REPO, timeout=300)
    if run.returncode != 0:
        raise SystemExit(f'make-game-lines.mjs failed: {run.stderr}')
    return {g['id']: g for g in json.loads(run.stdout)['games']}


# ---------------------------------------------------------------- board pixels
_TILES = {}


def board_image(fen, white_bottom):
    """512x512 playing area as displayed; a8 top-left when white is at the bottom, else h1 top-left."""
    labels = labels_from_fen(fen)
    if not white_bottom:
        labels = labels[::-1]
    img = np.zeros((BOARD, BOARD, 3), np.uint8)
    for k, label in enumerate(labels):
        row, col = divmod(k, 8)
        dark = bool((row + col) % 2)
        if (label, dark) not in _TILES:
            _TILES[(label, dark)] = np.asarray(render_tile(label, dark=dark))
        img[row*TILE:(row+1)*TILE, col*TILE:(col+1)*TILE] = _TILES[(label, dark)]
    return img


# ---------------------------------------------------------------- stress variants (round three)
# Each variant changes ONE thing versus the easy baseline (easy photometrics, jitter camera, no glare/hand).
STRESS_VARIANTS = ('style-unfamiliar', 'style-flat', 'theme-colours', 'last-move-highlight', 'coordinates',
                   'arrows-and-dots', 'lens-distortion', 'moire', 'motion-blur', 'small-board', 'mid-move', 'baseline')
STRESS_LEVELS = {'theme-colours': ('brown', 'blue', 'gray'), 'lens-distortion': (0.005, 0.01, 0.02),
                 'moire': (0.03, 0.06, 0.12), 'motion-blur': (3, 6, 12), 'small-board': (0.10, 0.12, 0.14)}
THEMES = {'classic': (LIGHT_TILE, DARK_TILE), 'brown': ((240, 217, 181), (181, 136, 99)),
          'blue': ((236, 242, 248), (120, 152, 190)), 'gray': ((196, 196, 196), (171, 171, 171))}
HIGHLIGHT, HIGHLIGHT_ALPHA = np.array([205.0, 210.0, 50.0]), 0.45
OVERLAY_P = 0.3
FILES = 'abcdefgh'


def square_name(k):
    """Chess index k (0 = a8 ... 63 = h1) -> 'e4'."""
    return FILES[k % 8] + str(8 - k // 8)


def display_rc(sq, white_bottom):
    r, c = 8 - int(sq[1]), FILES.index(sq[0])
    return (r, c) if white_bottom else (7 - r, 7 - c)


_SPRITES = {}


def classic_sprite(label, dark, style):
    """Existing artwork (render_tile) as RGB + alpha; alpha = pixels that differ from the bare tile."""
    key = ('c', label, dark, style)
    if key not in _SPRITES:
        tile = np.asarray(render_tile(label, dark=dark, style=style)).astype(float)
        alpha = (tile != np.array(DARK_TILE if dark else LIGHT_TILE)).any(-1).astype(float)
        _SPRITES[key] = (tile, alpha)
    return _SPRITES[key]


# Original solid silhouettes (64-unit tile coordinates), drawn without outlines and filling ~85% of the square.
_FLAT_SHAPES = {
    'P': [('ellipse', (23, 11, 41, 29)), ('ellipse', (21, 26, 43, 33)), ('poly', [(24, 30), (40, 30), (45, 52), (19, 52)])],
    'R': [('poly', [(17, 22), (47, 22), (45, 52), (19, 52)]),
          ('poly', [(13, 7), (21, 7), (21, 14), (28, 14), (28, 7), (36, 7), (36, 14), (43, 14), (43, 7), (51, 7),
                    (51, 25), (13, 25)])],
    'N': [('poly', [(13, 52), (15, 40), (26, 30), (14, 35), (7, 27), (19, 12), (23, 3), (30, 9), (42, 10), (53, 22),
                    (53, 40), (49, 52)])],
    'B': [('ellipse', (19, 9, 45, 41)), ('ellipse', (28, 2, 36, 10)), ('poly', [(24, 34), (40, 34), (47, 52), (17, 52)]),
          ('cut', [(37, 15), (29, 28)])],
    'Q': [('poly', [(9, 13), (20, 30), (24, 7), (32, 27), (40, 7), (44, 30), (55, 13), (49, 45), (15, 45)]),
          ('ellipse', (6, 9, 13, 16)), ('ellipse', (21, 3, 28, 10)), ('ellipse', (36, 3, 43, 10)),
          ('ellipse', (51, 9, 58, 16)), ('poly', [(16, 43), (48, 43), (47, 52), (17, 52)])],
    'K': [('poly', [(29, 2), (35, 2), (35, 8), (41, 8), (41, 14), (35, 14), (35, 20), (29, 20), (29, 14), (23, 14),
                    (23, 8), (29, 8)]),
          ('ellipse', (11, 18, 53, 46)), ('poly', [(17, 38), (47, 38), (47, 52), (17, 52)])],
}


def flat_sprite(label):
    key = ('f', label)
    if key not in _SPRITES:
        s = 4
        im = Image.new('RGBA', (64 * s, 64 * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        fill = (250, 250, 247, 255) if label.isupper() else (38, 38, 42, 255)
        for kind, geo in _FLAT_SHAPES[label.upper()]:
            if kind == 'poly':
                d.polygon([(x * s, y * s) for x, y in geo], fill=fill)
            elif kind == 'ellipse':
                d.ellipse(tuple(v * s for v in geo), fill=fill)
            else:  # transparent slit (bishop)
                d.line([(x * s, y * s) for x, y in geo], fill=(0, 0, 0, 0), width=3 * s)
        d.rounded_rectangle((9 * s, 51 * s, 55 * s, 59 * s), radius=3 * s, fill=fill)
        a = np.asarray(im.resize((64, 64), Image.Resampling.LANCZOS)).astype(float)
        _SPRITES[key] = (np.broadcast_to(np.array(fill[:3], float), (64, 64, 3)), a[..., 3] / 255)
    return _SPRITES[key]


def sprite(label, dark, style):
    return flat_sprite(label) if style == 'flat' else classic_sprite(label, dark, style)


def pseudo_targets(labels, k):
    """Empty squares a piece could move to, ignoring checks and pins (dots on empty squares only)."""
    piece = labels[k]
    r, c = divmod(k, 8)
    occ = lambda rr, cc: labels[rr * 8 + cc] != '.'
    inside = lambda rr, cc: 0 <= rr < 8 and 0 <= cc < 8
    out = []
    kind = piece.upper()
    if kind == 'P':
        step = -1 if piece.isupper() else 1
        if inside(r + step, c) and not occ(r + step, c):
            out.append((r + step, c))
            home = 6 if piece.isupper() else 1
            if r == home and not occ(r + 2 * step, c):
                out.append((r + 2 * step, c))
    elif kind in 'NK':
        deltas = ([(1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)] if kind == 'N'
                  else [(a, b) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b])
        out = [(r + a, c + b) for a, b in deltas if inside(r + a, c + b) and not occ(r + a, c + b)]
    else:
        dirs = {'R': [(1, 0), (-1, 0), (0, 1), (0, -1)], 'B': [(1, 1), (1, -1), (-1, 1), (-1, -1)]}
        dirs['Q'] = dirs['R'] + dirs['B']
        for a, b in dirs[kind]:
            rr, cc = r + a, c + b
            while inside(rr, cc) and not occ(rr, cc):
                out.append((rr, cc))
                rr, cc = rr + a, cc + b
    return [square_name(rr * 8 + cc) for rr, cc in out]


def plan_overlays(prng, fen, last_uci, next_uci):
    """~30% of positions: an arrow and legal-looking move dots UNRELATED to the last or next move."""
    if prng.random() >= OVERLAY_P:
        return None
    excl = {u[i:i + 2] for u in (last_uci, next_uci) if u for i in (0, 2)}
    names = [square_name(k) for k in range(64)]
    arrow = None
    for _ in range(200):
        a, b = (names[int(i)] for i in prng.integers(0, 64, 2))
        cheb = max(abs(FILES.index(a[0]) - FILES.index(b[0])), abs(int(a[1]) - int(b[1])))
        if cheb >= 2 and a not in excl and b not in excl:
            arrow = [a, b]
            break
    labels = labels_from_fen(fen)
    side_upper = fen.split()[1] == 'w'
    mine = [k for k in range(64) if labels[k] != '.' and labels[k].isupper() == side_upper
            and (next_uci is None or square_name(k) != next_uci[:2])]
    dots, hovered = [], None
    for k in prng.permutation(mine):
        t = [s for s in pseudo_targets(labels, int(k)) if s not in excl]
        if t:
            dots, hovered = sorted(t)[:8], square_name(int(k))
            break
    return dict(arrow=arrow, dots=dots, hovered=hovered)


_COORD_FONT = None


def stress_board(fen, white_bottom, opts):
    """512x512 playing area for a stress variant. opts: style, theme, highlight [sq, sq], coordinates,
    overlay {arrow, dots}, hide (square), moving (label, from, to: piece drawn halfway)."""
    global _COORD_FONT
    light, dark_c = THEMES[opts.get('theme', 'classic')]
    style = opts.get('style', 'classic')
    img = np.zeros((BOARD, BOARD, 3), float)
    for r in range(8):
        for c in range(8):
            img[r*TILE:(r+1)*TILE, c*TILE:(c+1)*TILE] = dark_c if (r + c) % 2 else light
    for sq in opts.get('highlight') or []:
        r, c = display_rc(sq, white_bottom)
        blk = img[r*TILE:(r+1)*TILE, c*TILE:(c+1)*TILE]
        blk[:] = blk * (1 - HIGHLIGHT_ALPHA) + HIGHLIGHT * HIGHLIGHT_ALPHA
    if opts.get('coordinates'):
        if _COORD_FONT is None:
            _COORD_FONT = ImageFont.load_default(size=12)
        pil = Image.fromarray(img.astype(np.uint8))
        d = ImageDraw.Draw(pil)
        for r in range(8):  # rank digit in the top-left corner of the left-hand column
            sq_rank = str(8 - r) if white_bottom else str(r + 1)
            d.text((3, r * TILE + 1), sq_rank, fill=tuple(light if r % 2 else dark_c), font=_COORD_FONT)
        for c in range(8):  # file letter in the bottom-right corner of the bottom row
            f = FILES[c] if white_bottom else FILES[7 - c]
            d.text((c * TILE + TILE - 10, 7 * TILE + TILE - 15), f, fill=tuple(dark_c if (7 + c) % 2 == 0 else light),
                   font=_COORD_FONT)
        img = np.asarray(pil, float).copy()
    labels = labels_from_fen(fen)
    for k, label in enumerate(labels):
        if label == '.' or square_name(k) == opts.get('hide'):
            continue
        r, c = display_rc(square_name(k), white_bottom)
        rgb, a = sprite(label, bool((r + c) % 2), style)
        blk = img[r*TILE:(r+1)*TILE, c*TILE:(c+1)*TILE]
        blk[:] = blk * (1 - a[..., None]) + rgb * a[..., None]
    mv = opts.get('moving')
    if mv:
        (r0, c0), (r1, c1) = display_rc(mv['from'], white_bottom), display_rc(mv['to'], white_bottom)
        y, x = int(round((r0 + r1) / 2 * TILE)), int(round((c0 + c1) / 2 * TILE))
        rgb, a = sprite(mv['label'], False, style)
        blk = img[y:y+TILE, x:x+TILE]
        blk[:] = blk * (1 - a[..., None]) + rgb * a[..., None]
    ov = opts.get('overlay')
    if ov:
        layer = Image.new('RGBA', (BOARD, BOARD), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for sq in ov['dots']:
            r, c = display_rc(sq, white_bottom)
            cx, cy = c * TILE + 32, r * TILE + 32
            d.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=(0, 0, 0, 56))
        if ov['arrow']:
            (ra, ca), (rb, cb) = (display_rc(s, white_bottom) for s in ov['arrow'])
            pa, pb = np.array([ca * TILE + 32, ra * TILE + 32.0]), np.array([cb * TILE + 32, rb * TILE + 32.0])
            u = (pb - pa) / np.linalg.norm(pb - pa)
            n = np.array([-u[1], u[0]])
            tip, base = pb - u * 6, pb - u * 30
            col = (255, 170, 0, 170)
            d.polygon([tuple(pa + n * 7), tuple(base + n * 7), tuple(base + n * 17), tuple(tip), tuple(base - n * 17),
                       tuple(base - n * 7), tuple(pa - n * 7)], fill=col)
        base_img = Image.fromarray(img.clip(0, 255).astype(np.uint8)).convert('RGBA')
        img = np.asarray(Image.alpha_composite(base_img, layer).convert('RGB'), float)
    return img.clip(0, 255).round().astype(np.uint8)


def lens_forward(pts, k1):
    """Barrel model: x_d = c + (x_u - c)(1 + k1 r^2), r = |x_u - c| / half-diagonal, k1 < 0."""
    c = np.array([(FRAME_W - 1) / 2, (FRAME_H - 1) / 2])
    d = np.asarray(pts, float) - c
    r2 = (d ** 2).sum(-1, keepdims=True) / (FRAME_W ** 2 / 4 + FRAME_H ** 2 / 4)
    return c + d * (1 + k1 * r2)


def lens_bow(k1, corners_u, mids_u):
    """Largest distance of a distorted edge midpoint from the chord between its distorted corners,
    as a fraction of the distorted board width."""
    cd, md = lens_forward(corners_u, k1), lens_forward(mids_u, k1)
    bw = cd[:, 0].max() - cd[:, 0].min()
    out = []
    for i in range(4):
        a, b, m = cd[i], cd[(i + 1) % 4], md[i]
        t = b - a
        out.append(abs(t[0] * (m - a)[1] - t[1] * (m - a)[0]) / np.linalg.norm(t))
    return max(out) / bw


def solve_k1(target, corners_u, mids_u):
    lo, hi = -0.8, 0.0  # keeps 1 + k1 r^2 > 0 over the whole frame (no fold-over)
    for _ in range(60):
        mid = (lo + hi) / 2
        if lens_bow(mid, corners_u, mids_u) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- camera
def camera(params, corners):
    """Homography canvas -> frame from explicit pose: yaw/pitch/roll (deg), board width fraction of
    the frame, and the frame position of the board centre."""
    yaw, pitch, roll = (math.radians(params[k]) for k in ('yaw', 'pitch', 'roll'))
    cy, sy, cp, sp, cr, sr = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch), math.cos(roll), math.sin(roll)
    R = (np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
         @ np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]]))
    center = corners.mean(0)
    target = params['width'] * FRAME_W
    dist = FOCAL * BOARD / target
    C = np.array([[1, 0, -center[0]], [0, 1, -center[1]], [0, 0, 1]])
    K = np.array([[FOCAL, 0, 0], [0, FOCAL, 0], [0, 0, 1]])
    for _ in range(4):
        h = K @ np.c_[R[:, 0], R[:, 1], np.array([0, 0, dist])] @ C
        q = apply_h(h, corners)
        dist *= (q[:, 0].max() - q[:, 0].min()) / target
    h = K @ np.c_[R[:, 0], R[:, 1], np.array([0, 0, dist])] @ C
    c = apply_h(h, corners).mean(0)
    h = np.array([[1, 0, params['cx'] - c[0]], [0, 1, params['cy'] - c[1]], [0, 0, 1]]) @ h
    return h / h[2, 2]


def camera_track(rng, cfg, mode, n, corners):
    """Per-frame pose list for one game; retries until every frame keeps the board in view."""
    for _ in range(200):
        base = dict(yaw=rng.uniform(-cfg['angle'], cfg['angle']), pitch=rng.uniform(-cfg['angle'], cfg['angle']),
                    roll=rng.uniform(-cfg['roll'], cfg['roll']), width=rng.uniform(*cfg['width']))
        h0 = camera(dict(base, cx=FRAME_W / 2, cy=FRAME_H / 2), corners)
        q = apply_h(h0, corners)
        bw = q[:, 0].max() - q[:, 0].min()
        margin = 12 + (0.15 * bw if mode == 'drift' else 0.03 * bw)
        half = np.array([FRAME_W / 2, FRAME_H / 2])
        lo = margin - (q.min(0) - half)
        hi = np.array([FRAME_W, FRAME_H]) - margin - (q.max(0) - half)
        if np.any(hi < lo):
            continue
        base['cx'], base['cy'] = (float(v) for v in rng.uniform(lo, hi))
        poses = []
        if mode == 'drift':
            ang = rng.uniform(0, 2 * math.pi)
            shift = rng.uniform(0.06, 0.11) * bw
            end = dict(yaw=rng.choice([-1, 1]) * rng.uniform(1.5, 3.5), pitch=rng.uniform(-2, 2),
                       roll=rng.choice([-1, 1]) * rng.uniform(1, 3), width=base['width'] * rng.uniform(-0.04, 0.04),
                       cx=shift * math.cos(ang), cy=shift * math.sin(ang))
            for i in range(n):
                t = i / max(1, n - 1)
                t = t * t * (3 - 2 * t)  # smooth slow drift
                poses.append({k: base[k] + end[k] * t for k in base})
        elif mode == 'jitter':
            for i in range(n):
                if i == 0:
                    poses.append(dict(base))
                    continue
                d = dict(yaw=rng.normal(0, 0.12), pitch=rng.normal(0, 0.12), roll=rng.normal(0, 0.1), width=0.0,
                         cx=rng.normal(0, 0.003 * bw), cy=rng.normal(0, 0.003 * bw))
                for _ in range(10):  # keep corner movement under 1.4% of board width
                    p = {k: base[k] + d[k] for k in base}
                    move = np.abs(apply_h(camera(p, corners), corners) - apply_h(camera(base, corners), corners)).max()
                    if move < 0.014 * bw:
                        break
                    d = {k: v * 0.5 for k, v in d.items()}
                poses.append(p)
        else:
            poses = [dict(base) for _ in range(n)]
        hs = [camera(p, corners) for p in poses]
        ok = all(((apply_h(h, corners) >= 12).all() and (apply_h(h, corners)[:, 0] <= FRAME_W - 13).all()
                  and (apply_h(h, corners)[:, 1] <= FRAME_H - 13).all()) for h in hs)
        if ok:
            return poses, hs
    raise RuntimeError('no camera track fits the frame')


# ---------------------------------------------------------------- frame rendering
def render_frame(frng, game_ctx, board, h, pose, difficulty, allow_occluders, dist_plan=None, srng=None):
    cfg = DIFFICULTY[difficulty]
    canvas, bcorners, screen = game_ctx['canvas_fn'](board)
    truth = apply_h(h, bcorners)
    board_w = float(truth[:, 0].max() - truth[:, 0].min())
    scale = board_w / BOARD
    hs, src = h, canvas
    if scale < 0.9:  # pre-downscale against aliasing (as make_screen_scenes.make_scene)
        f = min(1.0, scale * 1.3)
        im = Image.fromarray(canvas.astype(np.uint8))
        im = im.resize((max(2, int(round(im.size[0]*f))), max(2, int(round(im.size[1]*f)))), Image.Resampling.LANCZOS)
        fx, fy = im.size[0] / canvas.shape[1], im.size[1] / canvas.shape[0]
        src = np.asarray(im, float)
        hs = h @ np.array([[1/fx, 0, 0.5/fx - 0.5], [0, 1/fy, 0.5/fy - 0.5], [0, 0, 1]])
    p = game_ctx['grid'] @ np.linalg.inv(hs).T
    vals, inside = bilinear(src, p[:, 0] / p[:, 2], p[:, 1] / p[:, 2])
    vals = vals.reshape(FRAME_H, FRAME_W, 3) * game_ctx['gain']
    inside = inside.reshape(FRAME_H, FRAME_W, 1).astype(float)
    scr = Image.new('L', (FRAME_W, FRAME_H), 0)
    ImageDraw.Draw(scr).polygon([tuple(q) for q in apply_h(h, screen)], fill=255)
    bloom = np.asarray(scr.filter(ImageFilter.GaussianBlur(25)), float)[..., None] / 255
    scr_m = np.asarray(scr, float)[..., None] / 255
    img = game_ctx['room'] * (1 - inside) + vals * inside
    img = img + bloom * (1 - inside) * game_ctx['bloom']
    stress = game_ctx.get('stress')
    smeta = {}
    if stress and stress['name'] == 'moire':
        # Screen pixel grid: a fine 2D grating in SCREEN (canvas) coordinates, evaluated at the camera's
        # pixel centres. Its projected period is ~1 camera pixel, so it aliases into low-frequency fringes.
        q = game_ctx['grid'] @ np.linalg.inv(h).T
        u, v = q[:, 0] / q[:, 2], q[:, 1] / q[:, 2]
        period = 1.0 / ((board_w / BOARD) * game_ctx['moireF'])  # canvas px per grating cycle
        ph = srng.uniform(0, 2 * math.pi, 2)
        grat = 0.5 * (np.cos(2 * math.pi * u / period + ph[0]) + np.cos(2 * math.pi * v / period + ph[1]))
        gm = (1 + stress['level'] * grat).reshape(FRAME_H, FRAME_W, 1)
        img = img * (1 - scr_m) + img * gm * scr_m
        smeta['moire'] = {'amplitude': stress['level'], 'gratingCanvasPeriod': round(period, 4),
                          'projectedFreqCyclesPerPx': round(game_ctx['moireF'], 4)}
    prob = DISTURB[difficulty]
    meta = {'glare': None, 'hand': None, 'banding': None}
    ys = game_ctx['ys']
    if frng.random() < prob['banding']:
        amp = frng.uniform(0.02, 0.07) * (2 if difficulty == 'hard' else 1)
        per = frng.uniform(40, 160)
        band = 1 + amp * np.sin(2*np.pi*ys/per + frng.uniform(0, 6.28))[..., None]
        img = img * (1 - scr_m) + img * band * scr_m
        meta['banding'] = {'amplitude': round(amp, 3), 'periodPx': round(per, 1)}
    if dist_plan is None:  # legacy path: draws must stay exactly as in round one (byte-identical truth)
        if allow_occluders and frng.random() < prob['glare']:
            c = truth.mean(0) + frng.uniform(-0.4, 0.4, 2) * board_w
            sx, sy = board_w * frng.uniform(0.08, 0.35), board_w * frng.uniform(0.05, 0.25)
            amp = frng.uniform(60, 170)
            g = np.exp(-(((game_ctx['xs'] - c[0])/sx)**2 + ((ys - c[1])/sy)**2) / 2)[..., None]
            img = img + amp * g * scr_m
            meta['glare'] = {'center': [round(float(c[0]), 1), round(float(c[1]), 1)], 'amplitude': round(amp, 1)}
        if allow_occluders and frng.random() < prob['hand']:
            k = int(frng.integers(0, 4))
            img = hand(frng, img, truth[k], board_w, truth.mean(0) - truth[k])
            meta['hand'] = {'displayCorner': ('TL', 'TR', 'BR', 'BL')[k]}
    else:  # per-position mode: glare/hand fixed to the BOARD (display-normalised uv), planned by the caller
        gl, hd = dist_plan['glare'], dist_plan['hand']
        if gl is not None:
            uv_to_img = mss.homography([(0, 0), (1, 0), (1, 1), (0, 1)], truth)
            c = apply_h(uv_to_img, [gl['uv']])[0]
            sx, sy = board_w * gl['sx'], board_w * gl['sy']
            g = np.exp(-(((game_ctx['xs'] - c[0])/sx)**2 + ((ys - c[1])/sy)**2) / 2)[..., None]
            img = img + gl['amp'] * g * scr_m
            meta['glare'] = {'center': [round(float(c[0]), 1), round(float(c[1]), 1)], 'amplitude': round(gl['amp'], 1),
                             'boardUV': [round(gl['uv'][0], 4), round(gl['uv'][1], 4)]}
        if hd is not None:
            k = hd['corner']
            img = hand(np.random.default_rng(hd['seed']), img, truth[k], board_w, truth.mean(0) - truth[k])
            meta['hand'] = {'displayCorner': ('TL', 'TR', 'BR', 'BL')[k], 'shapeSeed': hd['seed'],
                            'anchor': [round(float(truth[k][0]), 1), round(float(truth[k][1]), 1)]}
        meta['sticky'] = dist_plan['sticky']
    if stress and stress['name'] == 'lens-distortion':
        k1 = game_ctx['k1']
        if 'lensMap' not in game_ctx:  # inverse map, fixed per game: distorted pixel -> undistorted source
            c = np.array([(FRAME_W - 1) / 2, (FRAME_H - 1) / 2])
            xd = game_ctx['grid'][:, :2]
            xu = xd.copy()
            for _ in range(8):
                r2 = ((xu - c) ** 2).sum(1, keepdims=True) / (FRAME_W ** 2 / 4 + FRAME_H ** 2 / 4)
                xu = c + (xd - c) / (1 + k1 * r2)
            game_ctx['lensMap'] = xu
        xu = game_ctx['lensMap']
        img = bilinear(img, xu[:, 0], xu[:, 1])[0].reshape(FRAME_H, FRAME_W, 3)
        mids_u = apply_h(h, [(bcorners[i] + bcorners[(i + 1) % 4]) / 2 for i in range(4)])
        smeta['lens'] = {'k1': round(k1, 6), 'model': 'x_d = c + (x_u - c)(1 + k1 r^2), c = frame centre, '
                         'r = |x_u - c| / half-diagonal',
                         'bowFrac': round(float(lens_bow(k1, truth, mids_u)), 5),
                         'undistortedDisplay': truth.tolist(), 'edgeMidpointsDisplay': lens_forward(mids_u, k1).tolist()}
        truth = lens_forward(truth, k1)
        board_w = float(truth[:, 0].max() - truth[:, 0].min())
    # Easy keeps total exposure low enough that white pieces on light squares do not clip to pure white
    # (make_screen_scenes allows up to ~1.6x, which erases them); medium/hard keep the inherited ranges.
    contrast = frng.uniform(0.6, 1.15) if difficulty != 'easy' else frng.uniform(0.85, 1.05)
    bright = frng.uniform(0.6, 1.25) if difficulty != 'easy' else frng.uniform(0.85, 1.08)
    mean = img.mean()
    img = ((img - mean) * contrast + mean) * bright
    if stress and stress['name'] == 'motion-blur':  # linear head-motion blur before sensor noise
        length, ang = stress['level'], float(srng.uniform(0, math.pi))
        acc = np.zeros_like(img)
        ts = np.linspace(-length / 2, length / 2, int(length) + 1)
        for t in ts:
            acc += np.roll(img, (int(round(t * math.sin(ang))), int(round(t * math.cos(ang)))), axis=(0, 1))
        img = acc / len(ts)
        smeta['motionBlur'] = {'lengthPx': length, 'angleDeg': round(math.degrees(ang), 2)}
    out = Image.fromarray(img.clip(0, 255).astype(np.uint8))
    blur = frng.uniform(*cfg['blur'])
    if blur > 0.05:
        out = out.filter(ImageFilter.GaussianBlur(blur))
    noise = frng.uniform(*cfg['noise'])
    arr = (np.asarray(out, float) + frng.normal(0, noise, (FRAME_H, FRAME_W, 1))
           + frng.normal(0, noise*0.5, (FRAME_H, FRAME_W, 3)))
    out = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    jpeg = None
    if difficulty == 'hard' or frng.random() < 0.3:
        jpeg = int(frng.integers(55, 90))
        buf = io.BytesIO(); out.save(buf, 'JPEG', quality=jpeg); buf.seek(0)
        out = Image.open(buf).convert('RGB')
    meta.update({'yawDeg': round(pose['yaw'], 3), 'pitchDeg': round(pose['pitch'], 3), 'rollDeg': round(pose['roll'], 3),
                 'boardWidthPx': round(board_w, 1), 'boardWidthFraction': round(board_w / FRAME_W, 4),
                 'blurSigma': round(blur, 2), 'noiseSigma': round(noise, 2), 'contrast': round(contrast, 3),
                 'brightness': round(bright, 3), 'screenGain': round(game_ctx['gain'], 3), 'jpegQuality': jpeg,
                 'keyboard': game_ctx['keyboard']})
    if stress:
        meta['stress'] = smeta
    return out, truth, meta


def plan_position_disturbances(prng, difficulty, position, per_pos):
    """Glare/hand plans for the 1+per_pos pictures of one position (per-position mode).

    Each picture draws independently. If the first picture is disturbed and a STICKY_P coin lands,
    the same glare spot / hand (fixed to the board) stays for every picture of the position. Otherwise
    a redrawn glare is placed at least 0.1 board width away from the previous one and a redrawn hand
    reaches over a different corner, so non-sticky disturbances visibly move. The start position
    (position 0) never gets glare or hand: a human confirms it."""
    prob = DISTURB[difficulty]
    sticky_coin = prng.random() < STICKY_P
    plans, last_glare, last_hand, sticky = [], None, None, False
    for j in range(1 + per_pos):
        if position == 0 or difficulty == 'easy':
            plans.append(dict(glare=None, hand=None, sticky=False))
            continue
        if j > 0 and sticky:
            plans.append(dict(plans[0]))
            continue
        glare = hand_plan = None
        if prng.random() < prob['glare']:
            for _ in range(50):
                uv = [float(v) for v in prng.uniform(0.1, 0.9, 2)]
                if last_glare is None or math.dist(uv, last_glare['uv']) >= 0.1:
                    break
            glare = dict(uv=uv, sx=float(prng.uniform(0.08, 0.35)), sy=float(prng.uniform(0.05, 0.25)),
                         amp=float(prng.uniform(60, 170)))
            last_glare = glare
        if prng.random() < prob['hand']:
            corners = [k for k in range(4) if last_hand is None or k != last_hand['corner']]
            hand_plan = dict(corner=int(prng.choice(corners)), seed=int(prng.integers(2**31)))
            last_hand = hand_plan
        if j == 0:
            sticky = sticky_coin and (glare is not None or hand_plan is not None)
        plans.append(dict(glare=glare, hand=hand_plan, sticky=sticky))
    return plans


def render_game(args):
    g, line, out = args
    t0 = time.time()
    seed, difficulty = g['seed'], g['difficulty']
    grng = np.random.default_rng([seed, 1])
    canvas_seed, room_seed = int(grng.integers(2**31)), int(grng.integers(2**31))
    canvas_fn = lambda board: (lambda a: (a[0], a[1], a[3]))(make_canvas(np.random.default_rng(canvas_seed), board))
    _, bcorners, _ = canvas_fn(None)
    # frame sequence: start, moves, and repeats inserted after some move frames
    moves = line['moves']
    rep_after = set()
    if g['repeats']:
        cand = list(range(1, len(moves)))
        rep_after = set(int(x) for x in grng.choice(cand, size=g['repeats'], replace=False))
    per_pos = g.get('perPosition')
    if per_pos is None:
        seq = [dict(kind='start', fen=line['startFen'], move=None)]
        for k, m in enumerate(moves):
            seq.append(dict(kind='move', fen=m['fen'], move=m))
            if k in rep_after:
                seq.append(dict(kind='repeat', fen=m['fen'], move=None))
    else:
        seq = []
        variant = (g.get('stress') or {}).get('name')
        positions = [(line['startFen'], None)] + [(m['fen'], m) for m in moves]
        for p, (fen, m) in enumerate(positions):
            plans = plan_position_disturbances(np.random.default_rng([seed, 3, p]), difficulty, p, per_pos)
            last = m['uci'] if m else None
            nxt = moves[p]['uci'] if p < len(moves) else None
            ov = (plan_overlays(np.random.default_rng([seed, 4, p]), fen, last, nxt)
                  if variant == 'arrows-and-dots' and p > 0 else None)
            if variant == 'mid-move' and p > 0 and p % 3 == 0:
                before = positions[p - 1][0]
                label = labels_from_fen(before)[(8 - int(last[1])) * 8 + FILES.index(last[0])]
                seq.append(dict(kind='transition', fen=fen, move=None, position=p, dist=plans[0], last=None,
                                overlay=None, moving=dict(label=label, frm=last[:2], to=last[2:4]),
                                boardFen=before, transitionMove=last))
            for j in range(1 + per_pos):
                kind = ('start' if p == 0 else 'move') if j == 0 else 'repeat'
                seq.append(dict(kind=kind, fen=fen, move=m if j == 0 else None, position=p, dist=plans[j],
                                last=last, overlay=ov))
    cfg = DIFFICULTY[difficulty]
    stress = g.get('stress')
    if stress and stress['name'] == 'small-board':
        cfg = dict(cfg, width=(stress['level'], stress['level']))
    poses, hs = camera_track(grng, cfg, g['cameraMode'], len(seq), bcorners)
    rrng = np.random.default_rng(room_seed)
    bg = room(rrng, difficulty == 'hard')
    keyboard = False
    avoid = int(max(apply_h(h, bcorners)[:, 1].max() for h in hs))
    if (rrng.random() < 0.5 or difficulty != 'easy') and avoid < FRAME_H - 120:
        bg = draw_keyboard(rrng, bg, avoid)
        keyboard = True
    xs, ys = np.meshgrid(np.arange(FRAME_W), np.arange(FRAME_H))
    ctx = dict(canvas_fn=canvas_fn, room=bg, keyboard=keyboard, xs=xs, ys=ys,
               grid=np.stack([xs, ys, np.ones_like(xs)], -1).reshape(-1, 3).astype(float),
               gain=float(grng.uniform(0.85, 1.0) if difficulty == 'easy' else grng.uniform(0.85, 1.2)),
               bloom=float(grng.uniform(10, 40)))
    if stress:  # stress-only randomness comes from its own streams, so baseline and style-unfamiliar
        ctx['stress'] = stress  # (same seed) get identical camera, room and noise
        srng_game = np.random.default_rng([seed, 6])
        ctx['moireF'] = float(srng_game.uniform(1.02, 1.05))
        if stress['name'] == 'lens-distortion':
            mids0 = apply_h(hs[0], [(bcorners[i] + bcorners[(i + 1) % 4]) / 2 for i in range(4)])
            ctx['k1'] = solve_k1(stress['level'], apply_h(hs[0], bcorners), mids0)
    gdir = Path(out) / 'games' / g['id']
    gdir.mkdir(parents=True, exist_ok=True)
    base_corners = None
    frames = []
    for i, f in enumerate(seq):
        frng = np.random.default_rng([seed, 2, i])
        board_opts = None
        if stress:
            name = stress['name']
            board_opts = dict(style={'style-unfamiliar': 'unfamiliar', 'style-flat': 'flat'}.get(name, 'classic'),
                              theme=stress['level'] if name == 'theme-colours' else 'classic',
                              coordinates=name == 'coordinates', overlay=f.get('overlay'),
                              highlight=[f['last'][:2], f['last'][2:4]] if name == 'last-move-highlight' and f.get('last')
                              else None)
            if f['kind'] == 'transition':
                mv = f['moving']
                board_opts.update(hide=mv['frm'], moving={'label': mv['label'], 'from': mv['frm'], 'to': mv['to']})
            board = stress_board(f.get('boardFen', f['fen']), g['whiteAtBottom'], board_opts)
        else:
            board = board_image(f['fen'], g['whiteAtBottom'])
        img, disp, meta = render_frame(frng, ctx, board, hs[i], poses[i], difficulty, allow_occluders=i > 0,
                                       dist_plan=f.get('dist'), srng=np.random.default_rng([seed, 5, i]))
        corners = disp if g['whiteAtBottom'] else disp[[2, 3, 0, 1]]
        if stress:
            sm = meta['stress']
            if 'lens' in sm:  # chess order a8,h8,h1,a1 and edges a8-h8, h8-h1, h1-a1, a1-a8
                order = [0, 1, 2, 3] if g['whiteAtBottom'] else [2, 3, 0, 1]
                sm['lens']['undistortedCorners'] = np.round(np.asarray(sm['lens'].pop('undistortedDisplay'))[order], 3).tolist()
                sm['lens']['edgeMidpoints'] = np.round(np.asarray(sm['lens'].pop('edgeMidpointsDisplay'))[order], 3).tolist()
                sm['lens']['note'] = ('board edges are curved: a 4-corner homography cannot be exact; '
                                      'corners are the distorted corner positions')
            if board_opts['highlight']:
                sm['highlight'] = board_opts['highlight']
            if board_opts['coordinates']:
                sm['coordinates'] = True
            if board_opts['overlay']:
                sm['overlay'] = board_opts['overlay']
            if f['kind'] == 'transition':
                sm['transition'] = {'piece': f['moving']['label'], 'from': f['moving']['frm'], 'to': f['moving']['to'],
                                    'drawnAt': 'halfway between the two square centres; origin already empty'}
        if base_corners is None:
            base_corners = corners
        bw = float(disp[:, 0].max() - disp[:, 0].min())
        meta['cornerShiftFromStartFrac'] = round(float(np.abs(corners - base_corners).max()) / bw, 4)
        name = f'{i:03d}.png'
        img.save(gdir / name, compress_level=3)
        m = f['move']
        disturbance = {'glare': meta['glare'] is not None, 'hand': meta['hand'] is not None,
                       'banding': meta['banding'] is not None}
        if 'sticky' in meta:
            disturbance['sticky'] = meta.pop('sticky')
        rec = {'index': i, 'file': f'games/{g["id"]}/{name}', 'kind': f['kind'], 'fen': f['fen'],
               'moveUci': m['uci'] if m else None, 'moveSan': m['san'] if m else None,
               'flags': list(m['flags']) if m else [],
               'corners': np.round(corners, 3).tolist(),
               'disturbance': disturbance,
               'scene': meta}
        if 'position' in f:
            rec['positionIndex'] = f['position']
        if stress:
            rec['transition'] = f['kind'] == 'transition'
            if rec['transition']:
                rec['transitionMove'] = f['transitionMove']
        frames.append(rec)
    record = {'id': g['id'], 'split': g['split'], 'seed': seed, 'difficulty': difficulty,
              'cameraMode': g['cameraMode'], 'whiteAtBottom': g['whiteAtBottom'], 'startFen': line['startFen'],
              'frames': frames}
    if stress:
        record['stress'] = dict(stress)
    return record, time.time() - t0


STRESS_NOTES = {
    'stress': 'per-game {name, level}; each variant changes ONE thing versus the easy baseline (jitter camera)',
    'transition': ("kind 'transition' (variant mid-move only): one extra picture BEFORE the settled pictures of a "
                   "position, showing the moving piece halfway between its squares with the origin already empty; "
                   "fen = position AFTER the move, transition: true, transitionMove = the move in progress. "
                   "Not a settled position: a pipeline should refuse it and must never accept a wrong move from it."),
    'lens': ('lens-distortion: corners are the DISTORTED corner positions; board edges are curved, so a 4-corner '
             'homography cannot be exact; scene.stress.lens has k1, the model and the distorted edge midpoints'),
}


def write_truth(out, games, per_position=None, extra=None):
    doc = {'schema': 'screen-game-truth-v1', 'frameSize': [FRAME_W, FRAME_H],
           'cornerOrder': 'a8,h8,h1,a1 corner of the playing area in image pixels (pixel centres at integer coords)',
           'simulated': 'All frames are SIMULATED renders (one 2D piece artwork, synthetic room); not camera evidence.',
           'generator': 'scripts/recognition/make_screen_game_scenes.py'}
    if per_position is not None:
        doc['repeatsPerPosition'] = per_position
        doc['positionIndex'] = '0 for the start position, +1 per move; the repeat pictures share the index'
        doc['sticky'] = (f'disturbance.sticky: the same glare spot / hand (fixed to the board) stays on all '
                         f'{1 + per_position} pictures of that position')
    doc.update(extra or {})
    doc['games'] = games
    (out / 'truth').mkdir(parents=True, exist_ok=True)
    (out / 'truth' / 'games.json').write_text(json.dumps(doc, indent=1))


def main_stress(args, out, workers):
    variants = list(STRESS_VARIANTS) if args.stress == 'all' else [v.strip() for v in args.stress.split(',')]
    if not set(variants) <= set(STRESS_VARIANTS):
        raise SystemExit(f'unknown stress variant in {variants}')
    splits = [s.strip() for s in args.splits.split(',')] if args.splits != 'smoke,dev,heldout' else ['stressdev', 'stressheld']
    if not set(splits) <= {'stressdev', 'stressheld'}:
        raise SystemExit('stress splits are stressdev, stressheld')
    games, n_frames, seconds, t_start = [], 0, 0.0, time.time()
    for split in splits:
        plan = stress_plan(split, SEED0[split], variants)[:args.limit_games]
        lines = game_lines(plan)
        jobs = [(g, lines[g['id']], str(out)) for g in plan]
        if workers > 1 and len(jobs) > 1:
            with Pool(min(workers, len(jobs))) as pool:
                results = pool.map(render_game, jobs)
        else:
            results = [render_game(j) for j in jobs]
        for rec, sec in results:
            games.append(rec)
            n_frames += len(rec['frames'])
            seconds += sec
        write_truth(out, games, 2, STRESS_NOTES)
        print(json.dumps({'split': split, 'games': len(results), 'frames': sum(len(r['frames']) for r, _ in results),
                          'wallSeconds': round(time.time() - t_start, 1)}), flush=True)
    print(json.dumps({'games': len(games), 'frames': n_frames, 'cpuSecondsPerFrame': round(seconds / max(1, n_frames), 2),
                      'wallSeconds': round(time.time() - t_start, 1), 'truth': str(out / 'truth' / 'games.json')}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='/Users/alexmunzon/chess-builds/pipeline-2026-11-15/scenes')
    ap.add_argument('--smoke-only', action='store_true')
    ap.add_argument('--workers', type=int, default=3, help='parallel processes (max 3 on the shared machine)')
    ap.add_argument('--splits', default='smoke,dev,heldout', help='comma list of base splits, built in this order')
    ap.add_argument('--suffix', default='', help="appended to split names, e.g. '2' -> smoke2, dev2, heldout2")
    ap.add_argument('--repeats-per-position', type=int, default=None,
                    help='N: show every position 1+N times in a row (default: legacy ~10%% random repeats)')
    ap.add_argument('--stress', default=None,
                    help="'all' or comma list of stress variants; builds stressdev,stressheld (see --splits)")
    ap.add_argument('--limit-games', type=int, default=None, help='stress: only the first N games per split')
    args = ap.parse_args()
    out = Path(args.out).resolve()
    if out == REPO or REPO in out.parents:
        raise SystemExit('Generated media must stay outside the repository.')
    legacy_root = Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15/scenes')
    if out == legacy_root and (args.suffix or args.repeats_per_position is not None or args.stress):
        raise SystemExit('The round-one scenes/ root is frozen; write new splits to another root.')
    if args.stress and out == legacy_root.parent / 'scenes-v2':
        raise SystemExit('scenes-v2/ is frozen; write stress splits to another root.')
    workers = max(1, min(3, args.workers))
    if args.stress:
        return main_stress(args, out, workers)
    bases = ['smoke'] if args.smoke_only else [s.strip() for s in args.splits.split(',') if s.strip()]
    if not set(bases) <= {'smoke', 'dev', 'heldout'}:
        raise SystemExit(f'unknown split in {bases}')
    per_pos = args.repeats_per_position
    if per_pos is not None and not 1 <= per_pos <= 5:
        raise SystemExit('--repeats-per-position must be 1..5')
    splits = [(b + args.suffix, 2 if b == 'smoke' else 12, SEED0.get(b + args.suffix)) for b in bases]
    for name, _, seed0 in splits:
        if seed0 is None:
            raise SystemExit(f'no seed range registered for split {name}')
    games, n_frames, seconds = [], 0, 0.0
    t_start = time.time()
    for split, n, seed0 in splits:
        plan = game_plan(split, n, seed0, per_pos)
        lines = game_lines(plan)
        jobs = [(g, lines[g['id']], str(out)) for g in plan]
        if workers > 1 and len(jobs) > 1:
            with Pool(min(workers, len(jobs))) as pool:
                results = pool.map(render_game, jobs)
        else:
            results = [render_game(j) for j in jobs]
        for rec, sec in results:
            games.append(rec)
            n_frames += len(rec['frames'])
            seconds += sec
        write_truth(out, games, per_pos)  # smoke truth is usable as soon as the smoke split finishes
        print(json.dumps({'split': split, 'games': len(results), 'frames': sum(len(r['frames']) for r, _ in results),
                          'wallSeconds': round(time.time() - t_start, 1)}), flush=True)
    print(json.dumps({'games': len(games), 'frames': n_frames, 'cpuSecondsPerFrame': round(seconds / max(1, n_frames), 2),
                      'wallSeconds': round(time.time() - t_start, 1), 'truth': str(out / 'truth' / 'games.json')}))


if __name__ == '__main__':
    main()
