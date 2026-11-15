#!/usr/bin/env python3
"""Seeded simulated head-camera frames of a chess board shown on a glowing screen.

Experiment-only scene generator for native/ScreenBoardVision. It never edits the source corpus.

1. Clean boards: for each distinct position in the read-only synthetic corpus it picks one
   unoccluded frame, maps the 8x8 playing area (panel pixels 64..576) back to a flat 512x512
   image with the evaluator quad, and keeps ONLY that area. The four colored corner markers
   sit at panel (32,32)/(608,32)/... outside the playing area, so they are cropped away.
2. Scenes: each clean board is placed on a screen canvas (UI page + dark bezel), projected into
   a 1920x1080 room frame through a known camera homography (yaw/pitch up to +-35 deg), and
   degraded (clutter, glow, brightness/contrast, blur, noise, optional glare, hand occluder,
   crude refresh banding, JPEG). Ground truth goes to a separate truth JSON.
3. Sanity: 5 original corpus PNGs with the markers painted out, plus their truth.

Pixel convention for all corners: pixel (i, j) has its center at continuous coordinate (i, j).
"""
import argparse
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

CORPUS = Path('/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/'
              'outputs/simulation-2026-11-11/corpus')
FRAME_W, FRAME_H = 1920, 1080
BOARD = 512
FOCAL = 1400.0
DIFFICULTY = {
    #           max |yaw|,|pitch|  board width fraction  roll  blur sigma   noise sigma  glare  hand
    'easy':   dict(angle=15, width=(0.35, 0.60), roll=4, blur=(0.0, 0.6), noise=(1, 3), glare=0.0, hand=0.0),
    'medium': dict(angle=25, width=(0.22, 0.60), roll=8, blur=(0.3, 1.2), noise=(2, 6), glare=0.4, hand=0.3),
    'hard':   dict(angle=35, width=(0.15, 0.60), roll=12, blur=(0.6, 2.0), noise=(4, 10), glare=0.7, hand=0.6),
}


def homography(src, dst):
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u*x, -u*y, -u])
        rows.append([0, 0, 0, x, y, 1, -v*x, -v*y, -v])
    _, _, vt = np.linalg.svd(np.asarray(rows, float))
    h = vt[-1].reshape(3, 3)
    return h / h[2, 2]


def apply_h(h, pts):
    pts = np.asarray(pts, float)
    p = np.c_[pts, np.ones(len(pts))] @ h.T
    return p[:, :2] / p[:, 2:3]


def bilinear(img, x, y):
    """Sample HxWxC float image at index coordinates; returns values and inside mask."""
    hgt, wid = img.shape[:2]
    inside = (x >= -0.5) & (x <= wid - 0.5) & (y >= -0.5) & (y <= hgt - 0.5)
    xc = np.clip(x, 0, wid - 1.001)
    yc = np.clip(y, 0, hgt - 1.001)
    x0 = np.floor(xc).astype(int)
    y0 = np.floor(yc).astype(int)
    fx = (xc - x0)[..., None]
    fy = (yc - y0)[..., None]
    a = img[y0, x0]; b = img[y0, x0+1]; c = img[y0+1, x0]; d = img[y0+1, x0+1]
    return (a*(1-fx)*(1-fy) + b*fx*(1-fy) + c*(1-fx)*fy + d*fx*fy), inside


def panel_to_image(quad):
    # Pillow continuous coords (pixel center +0.5) -> our convention (center at integer).
    return homography([(0, 0), (640, 0), (640, 640), (0, 640)], np.asarray(quad, float) - 0.5)


def extract_boards(out):
    truth = json.loads((CORPUS / 'evaluator' / 'truth.json').read_text())
    best = {}
    for f in truth['frames']:
        sc = f.get('scene', {})
        if sc.get('occlusions') or 'quad' not in sc:
            continue
        key = f['fen'].split()[0]
        rank = (sc.get('style', 'classic') != 'classic', sc.get('blur', 0), abs(sc.get('brightness', 1) - 1))
        if key not in best or rank < best[key][0]:
            best[key] = (rank, f)
    boards = []
    (out / 'boards').mkdir(parents=True, exist_ok=True)
    for key in sorted(best, key=lambda k: best[k][1]['id']):
        f = best[key][1]
        src = np.asarray(Image.open(CORPUS / 'pixels' / f['file']).convert('RGB'), float)
        h = panel_to_image(f['scene']['quad'])
        u, v = np.meshgrid(np.arange(BOARD) + 64.5, np.arange(BOARD) + 64.5)
        p = apply_h(h, np.c_[u.ravel(), v.ravel()])
        vals, _ = bilinear(src, p[:, 0], p[:, 1])
        img = vals.reshape(BOARD, BOARD, 3).clip(0, 255).astype(np.uint8)
        name = f'board-{f["id"]}.png'
        Image.fromarray(img).save(out / 'boards' / name)
        boards.append({'file': name, 'sourceFrame': f['file'], 'placement': key,
                       'corpusSplit': f['split']})
    return boards


def rand_color(rng, lo, hi):
    return tuple(int(c) for c in rng.integers(lo, hi, 3))


def make_canvas(rng, board):
    """Flat screen: dark bezel around a UI page that contains the board. Returns RGB array,
    board corners in canvas index coords, and the bezel/screen quads."""
    s = BOARD
    sw = int(s * rng.uniform(1.35, 2.0)); sh = int(s * rng.uniform(1.08, 1.25))
    bez = int(sw * rng.uniform(0.02, 0.06))
    dark = rng.random() < 0.6
    page = rand_color(rng, 25, 55) if dark else rand_color(rng, 215, 245)
    canvas = Image.new('RGB', (sw + 2*bez, sh + 2*bez), rand_color(rng, 8, 28))
    d = ImageDraw.Draw(canvas)
    d.rectangle((bez, bez, bez+sw-1, bez+sh-1), fill=page)
    top = int(rng.uniform(0.03, 0.08) * sh)
    d.rectangle((bez, bez, bez+sw-1, bez+top), fill=tuple(max(0, min(255, c + (18 if dark else -25))) for c in page))
    bx = bez + int(rng.uniform(0.03, 0.12) * sw)
    by = bez + top + int(rng.uniform(0.0, 1.0) * max(1, sh - s - top - 4))
    # side panel with fake text lines (move list) to the right of the board
    px0 = bx + s + int(0.03*sw)
    if px0 < bez + sw - 40:
        panel = tuple(max(0, min(255, c + (14 if dark else -14))) for c in page)
        d.rectangle((px0, by, bez+sw-int(0.03*sw), by+s), fill=panel)
        ink = (200, 200, 200) if dark else (60, 60, 60)
        y = by + 12
        while y < by + s - 12:
            w = int(rng.uniform(0.2, 0.8) * (bez + sw - int(0.03*sw) - px0 - 20))
            d.rectangle((px0+10, y, px0+10+w, y+5), fill=ink)
            y += int(rng.uniform(14, 24))
    if board is not None:
        canvas.paste(Image.fromarray(board), (bx, by))
    arr = np.asarray(canvas, float)
    corners = np.array([[bx-0.5, by-0.5], [bx+s-0.5, by-0.5], [bx+s-0.5, by+s-0.5], [bx-0.5, by+s-0.5]])
    W, H = arr.shape[1], arr.shape[0]
    outer = np.array([[-0.5, -0.5], [W-0.5, -0.5], [W-0.5, H-0.5], [-0.5, H-0.5]])
    screen = np.array([[bez-0.5, bez-0.5], [bez+sw-0.5, bez-0.5], [bez+sw-0.5, bez+sh-0.5], [bez-0.5, bez+sh-0.5]])
    return arr, corners, outer, screen


def camera_h(rng, cfg, corners):
    yaw, pitch = (math.radians(rng.uniform(-cfg['angle'], cfg['angle'])) for _ in range(2))
    roll = math.radians(rng.uniform(-cfg['roll'], cfg['roll']))
    cy, sy, cp, sp, cr, sr = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch), math.cos(roll), math.sin(roll)
    R = (np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
         @ np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]]))
    center = corners.mean(0)
    target = rng.uniform(*cfg['width']) * FRAME_W
    dist = FOCAL * BOARD / target
    for _ in range(4):
        C = np.array([[1, 0, -center[0]], [0, 1, -center[1]], [0, 0, 1]])
        K = np.array([[FOCAL, 0, 0], [0, FOCAL, 0], [0, 0, 1]])
        h = K @ np.c_[R[:, 0], R[:, 1], R[:, 2]*0 + np.array([0, 0, dist])] @ C
        q = apply_h(h, corners)
        width = q[:, 0].max() - q[:, 0].min()
        dist *= width / target
    lo = -q.min(0) + 12; hi = np.array([FRAME_W, FRAME_H]) - q.max(0) - 12
    if np.any(hi < lo):
        return None
    t = rng.uniform(lo, hi)
    h = np.array([[1, 0, t[0]], [0, 1, t[1]], [0, 0, 1]]) @ h
    return h / h[2, 2], math.degrees(yaw), math.degrees(pitch), math.degrees(roll)


def room(rng, hard):
    y = np.linspace(0, 1, FRAME_H)[:, None, None]
    a = np.array(rand_color(rng, 20, 120), float); b = np.array(rand_color(rng, 10, 90), float)
    if hard and rng.random() < 0.5:
        a = a + 60; b = b + 40  # daylight room: less screen-to-room contrast
    bg = Image.fromarray((a*(1-y) + b*y + np.zeros((1, FRAME_W, 1))).clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(bg)
    for _ in range(int(rng.integers(5, 12))):  # furniture / posters
        x0, y0 = rng.integers(-200, FRAME_W), rng.integers(-200, FRAME_H)
        d.rectangle((x0, y0, x0 + rng.integers(80, 600), y0 + rng.integers(60, 500)), fill=rand_color(rng, 10, 200))
    # window with mullions (a second, non-board rectangle grid)
    wx, wy = rng.integers(0, FRAME_W - 400), rng.integers(0, FRAME_H // 2)
    ww, wh = rng.integers(250, 600), rng.integers(200, 420)
    d.rectangle((wx, wy, wx+ww, wy+wh), fill=rand_color(rng, 170, 250))
    cols, rws = int(rng.integers(2, 4)), int(rng.integers(1, 3))
    for i in range(1, cols):
        d.rectangle((wx + i*ww//cols - 4, wy, wx + i*ww//cols + 4, wy+wh), fill=(230, 230, 225))
    for j in range(1, rws + 1):
        d.rectangle((wx, wy + j*wh//(rws+1) - 4, wx+ww, wy + j*wh//(rws+1) + 4), fill=(230, 230, 225))
    return np.asarray(bg, float)


def draw_keyboard(rng, img, avoid):
    """Keyboard: dark slab with a 5x14 key grid, sheared, drawn into the lower frame."""
    kb = Image.new('RGBA', (900, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(kb)
    d.rounded_rectangle((0, 0, 899, 299), 18, fill=rand_color(rng, 15, 45) + (255,))
    key = rand_color(rng, 40, 90) + (255,)
    for r in range(5):
        for c in range(14):
            d.rounded_rectangle((14 + c*63, 14 + r*56, 14 + c*63 + 54, 14 + r*56 + 46), 6, fill=key)
    scale = rng.uniform(0.5, 1.0)
    kb = kb.resize((int(900*scale), int(300*scale)), Image.Resampling.BILINEAR)
    kb = kb.transform(kb.size, Image.Transform.AFFINE, (1, rng.uniform(-0.3, 0.3), 0, 0, 1, 0), Image.Resampling.BILINEAR)
    x = int(rng.integers(0, FRAME_W - kb.size[0]))
    y = int(max(avoid + 20, FRAME_H - kb.size[1] - rng.integers(0, 60)))
    if y + 40 >= FRAME_H:
        return img
    base = Image.fromarray(img.clip(0, 255).astype(np.uint8))
    base.paste(kb, (x, y), kb)
    return np.asarray(base, float)


def hand(rng, img, corner, side, toward):
    """Skin-colored palm + fingers reaching over one board corner."""
    skin = np.array(rand_color(rng, 120, 230), float) * np.array([1.0, 0.78, 0.62])
    mask = Image.new('L', (FRAME_W, FRAME_H), 0)
    d = ImageDraw.Draw(mask)
    reach = side * rng.uniform(0.10, 0.22)
    out = -toward / (np.linalg.norm(toward) + 1e-9)
    tip = corner - out * reach
    palm = corner + out * side * 0.25
    r = side * 0.18
    d.ellipse((palm[0]-r, palm[1]-r*0.8, palm[0]+r, palm[1]+r*0.8), fill=255)
    perp = np.array([-out[1], out[0]])
    for k in np.linspace(-1, 1, 4):
        base = palm + perp * k * r * 0.7
        end = tip + perp * k * r * 0.45
        d.line([tuple(base), tuple(end)], fill=255, width=max(4, int(side*0.045)))
        d.ellipse((end[0]-side*0.022, end[1]-side*0.022, end[0]+side*0.022, end[1]+side*0.022), fill=255)
    m = np.asarray(mask.filter(ImageFilter.GaussianBlur(1.2)), float)[..., None] / 255
    shade = 0.75 + 0.35 * np.linspace(0, 1, FRAME_W)[None, :, None]
    return img * (1 - m) + skin * shade * m


NEGATIVE_KINDS = ('no-board', 'draughts-10x10', 'checker-6x6', 'checker-9x9')


def make_negative_board(rng, kind):
    """Non-chess content for the 512x512 board slot: nothing, or a checker that is not 8x8."""
    if kind == 'no-board':
        return None
    n = {'draughts-10x10': 10, 'checker-6x6': 6, 'checker-9x9': 9}[kind]
    light, dark = rand_color(rng, 180, 245), rand_color(rng, 60, 140)
    img = Image.new('RGB', (BOARD, BOARD), light)
    d = ImageDraw.Draw(img)
    edges = [round(i * BOARD / n) for i in range(n + 1)]
    for r in range(n):
        for c in range(n):
            if (r + c) % 2:
                d.rectangle((edges[c], edges[r], edges[c+1]-1, edges[r+1]-1), fill=dark)
            if kind == 'draughts-10x10' and (r + c) % 2 and (r < 4 or r > 5):
                cx, cy, rad = (edges[c]+edges[c+1])/2, (edges[r]+edges[r+1])/2, BOARD/n*0.33
                d.ellipse((cx-rad, cy-rad, cx+rad, cy+rad), fill=(30, 30, 30) if r < 4 else (240, 240, 230))
    return np.asarray(img)


def make_scene(rng, board, difficulty):
    cfg = DIFFICULTY[difficulty]
    canvas, bcorners, outer, screen = make_canvas(rng, board)
    cam = None
    while cam is None:
        cam = camera_h(rng, cfg, bcorners)
    h, yaw, pitch, roll = cam
    truth = apply_h(h, bcorners)
    board_w = float(truth[:, 0].max() - truth[:, 0].min())
    # Screen emission: gain, pre-downscale canvas to avoid aliasing when far away.
    gain = rng.uniform(0.85, 1.25)
    scale = board_w / BOARD
    hs = h
    src = canvas
    if scale < 0.9:
        f = min(1.0, scale * 1.3)
        im = Image.fromarray(canvas.astype(np.uint8))
        im = im.resize((max(2, int(round(im.size[0]*f))), max(2, int(round(im.size[1]*f)))), Image.Resampling.LANCZOS)
        fx = im.size[0] / canvas.shape[1]; fy = im.size[1] / canvas.shape[0]
        src = np.asarray(im, float)
        # new index -> old index: old = (new + 0.5)/f - 0.5
        hs = h @ np.array([[1/fx, 0, 0.5/fx - 0.5], [0, 1/fy, 0.5/fy - 0.5], [0, 0, 1]])
    hinv = np.linalg.inv(hs)
    xs, ys = np.meshgrid(np.arange(FRAME_W), np.arange(FRAME_H))
    p = np.stack([xs, ys, np.ones_like(xs)], -1).reshape(-1, 3) @ hinv.T
    vals, inside = bilinear(src, p[:, 0] / p[:, 2], p[:, 1] / p[:, 2])
    vals = vals.reshape(FRAME_H, FRAME_W, 3) * gain
    inside = inside.reshape(FRAME_H, FRAME_W, 1).astype(float)
    # screen region mask (page area, not bezel) for glow/glare/banding
    scr = Image.new('L', (FRAME_W, FRAME_H), 0)
    ImageDraw.Draw(scr).polygon([tuple(q) for q in apply_h(h, screen)], fill=255)
    scr_m = np.asarray(scr, float)[..., None] / 255
    img = room(rng, difficulty == 'hard')
    img = img * (1 - inside) + vals * inside
    bloom = np.asarray(Image.fromarray((scr_m[..., 0]*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(25)), float)[..., None]/255
    img = img + bloom * (1 - inside) * rng.uniform(10, 40)
    meta = {'glare': None, 'hand': None, 'banding': None, 'keyboard': False}
    if rng.random() < 0.5 or difficulty != 'easy':
        avoid = int(truth[:, 1].max())
        if avoid < FRAME_H - 120:
            img = draw_keyboard(rng, img, avoid)
            meta['keyboard'] = True
    if difficulty != 'easy' and rng.random() < 0.5:
        amp = rng.uniform(0.02, 0.07) * (2 if difficulty == 'hard' else 1)
        per = rng.uniform(40, 160)
        band = 1 + amp * np.sin(2*np.pi*ys/per + rng.uniform(0, 6.28))[..., None]
        img = img * (1 - scr_m) + img * band * scr_m
        meta['banding'] = {'amplitude': round(amp, 3), 'periodPx': round(per, 1)}
    if rng.random() < cfg['glare']:
        c = truth.mean(0) + rng.uniform(-0.4, 0.4, 2) * board_w
        sx, sy = board_w * rng.uniform(0.08, 0.35), board_w * rng.uniform(0.05, 0.25)
        amp = rng.uniform(60, 170)
        g = np.exp(-(((xs - c[0])/sx)**2 + ((ys - c[1])/sy)**2) / 2)[..., None]
        img = img + amp * g * scr_m
        meta['glare'] = {'center': [round(float(c[0]), 1), round(float(c[1]), 1)], 'amplitude': round(amp, 1)}
    if rng.random() < cfg['hand']:
        k = int(rng.integers(0, 4))
        img = hand(rng, img, truth[k], board_w, truth.mean(0) - truth[k])
        meta['hand'] = {'corner': k}
    # photometric: brightness/contrast, blur, noise, optional JPEG
    contrast = rng.uniform(0.6, 1.15) if difficulty != 'easy' else rng.uniform(0.85, 1.1)
    bright = rng.uniform(0.6, 1.25) if difficulty != 'easy' else rng.uniform(0.85, 1.15)
    mean = img.mean()
    img = ((img - mean) * contrast + mean) * bright
    out = Image.fromarray(img.clip(0, 255).astype(np.uint8))
    blur = rng.uniform(*cfg['blur'])
    if blur > 0.05:
        out = out.filter(ImageFilter.GaussianBlur(blur))
    noise = rng.uniform(*cfg['noise'])
    arr = np.asarray(out, float) + rng.normal(0, noise, (FRAME_H, FRAME_W, 1)) + rng.normal(0, noise*0.5, (FRAME_H, FRAME_W, 3))
    out = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    jpeg = None
    if difficulty == 'hard' or rng.random() < 0.3:
        jpeg = int(rng.integers(55, 90))
        buf = io.BytesIO(); out.save(buf, 'JPEG', quality=jpeg); buf.seek(0)
        out = Image.open(buf).convert('RGB')
    meta.update({'yawDeg': round(yaw, 2), 'pitchDeg': round(pitch, 2), 'rollDeg': round(roll, 2),
                 'boardWidthPx': round(board_w, 1), 'boardWidthFraction': round(board_w / FRAME_W, 3),
                 'blurSigma': round(blur, 2), 'noiseSigma': round(noise, 2), 'contrast': round(contrast, 3),
                 'brightness': round(bright, 3), 'screenGain': round(gain, 3), 'jpegQuality': jpeg})
    return out, truth, meta


def sanity(out):
    """5 original corpus frames with the four markers painted over (panel ring color)."""
    truth = json.loads((CORPUS / 'evaluator' / 'truth.json').read_text())
    frames = [f for f in truth['frames'] if not f['scene'].get('occlusions')][:: 13][:5]
    (out / 'sanity').mkdir(parents=True, exist_ok=True)
    rows = []
    for f in frames:
        img = Image.open(CORPUS / 'pixels' / f['file']).convert('RGB')
        arr = np.asarray(img, float)
        h = panel_to_image(f['scene']['quad'])
        d = ImageDraw.Draw(img)
        for cx, cy in [(32, 32), (608, 32), (608, 608), (32, 608)]:
            ring = apply_h(h, [(cx + 22*math.cos(a), cy + 22*math.sin(a)) for a in np.linspace(0, 6.28, 24)])
            col = tuple(int(c) for c in np.median([arr[int(round(y)), int(round(x))] for x, y in ring], 0))
            disc = apply_h(h, [(cx + 19*math.cos(a), cy + 19*math.sin(a)) for a in np.linspace(0, 6.28, 32)])
            d.polygon([tuple(q) for q in disc], fill=col)
        img.save(out / 'sanity' / f['file'])
        corners = apply_h(h, [(64, 64), (576, 64), (576, 576), (64, 576)])  # playing-area edges
        rows.append({'id': 'sanity-' + f['id'], 'file': 'sanity/' + f['file'], 'split': 'sanity',
                     'difficulty': 'sanity', 'corners': np.round(corners, 3).tolist(),
                     'boardWidthPx': round(float(corners[:, 0].max() - corners[:, 0].min()), 1)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='/Users/alexmunzon/chess-builds/screen-board-2026-11-15')
    ap.add_argument('--dev', type=int, default=210)
    ap.add_argument('--heldout', type=int, default=150)
    ap.add_argument('--negatives', type=int, default=24, help='per split')
    args = ap.parse_args()
    out = Path(args.out)
    boards = extract_boards(out)
    if len(boards) < 20:
        raise SystemExit(f'only {len(boards)} distinct boards')
    # Disjoint positions: about 70% of boards for development, the rest held out.
    cut = int(round(len(boards) * 0.7))
    dev_boards, held_boards = boards[:cut], boards[cut:]
    scenes = []
    for split, n, pool, seed0 in (('dev', args.dev, dev_boards, 0), ('heldout', args.heldout, held_boards, 100000)):
        (out / 'scenes' / split).mkdir(parents=True, exist_ok=True)
        for i in range(n):
            seed = seed0 + i
            rng = np.random.default_rng(seed)
            difficulty = ('easy', 'medium', 'hard')[i % 3]
            b = pool[i % len(pool)]
            board = np.asarray(Image.open(out / 'boards' / b['file']).convert('RGB'))
            img, corners, meta = make_scene(rng, board, difficulty)
            name = f'{split}-{i:04d}.png'
            img.save(out / 'scenes' / split / name)
            scenes.append({'id': f'{split}-{i:04d}', 'file': f'scenes/{split}/{name}', 'split': split, 'seed': seed,
                           'difficulty': difficulty, 'board': b['file'], 'corners': np.round(corners, 3).tolist(), **meta})
            if i % 30 == 0:
                print(split, i, flush=True)
    # Negative controls: no board, or a checker that is not 8x8. Separate seeds; a detector
    # 'found' on any of these is a false accept.
    for split, n, seed0 in (('dev', args.negatives, 50000), ('heldout', args.negatives, 150000)):
        for i in range(n):
            seed = seed0 + i
            rng = np.random.default_rng(seed)
            difficulty = ('easy', 'medium', 'hard')[i % 3]
            kind = NEGATIVE_KINDS[i % len(NEGATIVE_KINDS)]
            img, corners, meta = make_scene(rng, make_negative_board(rng, kind), difficulty)
            name = f'{split}-neg-{i:04d}.png'
            img.save(out / 'scenes' / split / name)
            scenes.append({'id': f'{split}-neg-{i:04d}', 'file': f'scenes/{split}/{name}', 'split': split, 'seed': seed,
                           'difficulty': difficulty, 'negative': kind, 'board': None,
                           'distractorCorners': np.round(corners, 3).tolist(), 'corners': None, **meta})
    (out / 'truth').mkdir(parents=True, exist_ok=True)
    doc = {'schema': 'screen-board-truth-v1', 'frameSize': [FRAME_W, FRAME_H], 'focalPx': FOCAL,
           'cornerOrder': 'TL,TR,BR,BL of the board as displayed; pixel centers at integer coordinates',
           'markerHandling': 'boards are the 8x8 playing area only, unwarped from corpus frames; markers lie outside it',
           'boards': boards, 'scenes': scenes, 'sanity': sanity(out)}
    (out / 'truth' / 'truth.json').write_text(json.dumps(doc, indent=1))
    print(json.dumps({'scenes': len(scenes), 'boards': len(boards), 'dev': len(dev_boards), 'heldout': len(held_boards)}))


if __name__ == '__main__':
    main()
