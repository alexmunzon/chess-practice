#!/usr/bin/env python3
"""Build mock-glasses test videos from this project's own synthetic chess frames.

Output format is the one Meta's simulated glasses accept: H.265/HEVC in .mp4, tag hvc1,
yuv420p, portrait 9:16, 30 fps, no audio. Each source frame (in the manifest's play order,
interruption frames included) is scaled to a square board centred in the portrait frame, with
neutral gray bands above and below. Each band carries the same frame-index code ("nonce").

Nonce layout (reference size 720x1280; everything scales with width W, block = W/18):
  a 16 x 4 grid of 40 px blocks at x=40, y=60 (top band) and y=1060 (bottom band).
  row 0  start pattern  B W B W ... (16 blocks)
  row 1-2 16 Manchester bits (1 = black,white; 0 = white,black):
          8-bit source frame index then CRC-8 (poly 0x07, init 0xFF) of that byte
  row 3  stop pattern   W B W B ...
A block must read clearly black or clearly white; any gray block, broken Manchester pair, bad
start/stop row, bad CRC or top/bottom disagreement makes the reader abstain.

Usage:
  make-mock-glasses-video.py --all OUTDIR [options]   (both games, 720x1280 and 504x896)
  make-mock-glasses-video.py MANIFEST OUT.mp4 [--size 720x1280|504x896] [--hold 2.0]
      [--fps 30] [--encoder libx265|hevc_videotoolbox] [--crf 20]
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image

FFMPEG = os.environ.get("FFMPEG", "/usr/local/bin/ffmpeg")
GRAY = 128
REF_W, REF_H = 720, 1280
COLS, ROWS = 16, 4
BLOCK = 40            # at reference width
GRID_X = 40
TOP_Y = 60
BOTTOM_Y = 1060


def crc8(byte):
    crc = 0xFF ^ byte
    for _ in range(8):
        crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def nonce_bits(index):
    if not 0 <= index <= 255:
        raise ValueError("frame index must fit in 8 bits")
    value = (index << 8) | crc8(index)
    return [(value >> (15 - i)) & 1 for i in range(16)]


def nonce_pattern(index):
    """4x16 array of 0 (black) / 1 (white) blocks."""
    grid = np.zeros((ROWS, COLS), dtype=np.uint8)
    grid[0] = [(c % 2) for c in range(COLS)]          # B W B W ...
    grid[3] = [1 - (c % 2) for c in range(COLS)]      # W B W B ...
    blocks = []
    for bit in nonce_bits(index):
        blocks += [0, 1] if bit else [1, 0]
    grid[1] = blocks[:16]
    grid[2] = blocks[16:]
    return grid


def layout(width, height):
    """Pixel geometry for a frame of the given size (proportional to the 720x1280 reference)."""
    s = width / REF_W
    if abs(height / width - REF_H / REF_W) > 1e-6:
        raise ValueError("frame must be 9:16 portrait")
    board_top = (height - width) / 2
    return {
        "scale": s,
        "block": BLOCK * s,
        "grid_x": GRID_X * s,
        "band_y": [TOP_Y * s, BOTTOM_Y * s],
        "board": (0, board_top, width, board_top + width),
    }


def draw_nonce(arr, index, width, height):
    lay = layout(width, height)
    grid = nonce_pattern(index)
    b = lay["block"]
    for y0 in lay["band_y"]:
        for r in range(ROWS):
            for c in range(COLS):
                x1, y1 = round(lay["grid_x"] + c * b), round(y0 + r * b)
                x2, y2 = round(lay["grid_x"] + (c + 1) * b), round(y0 + (r + 1) * b)
                arr[y1:y2, x1:x2] = 255 if grid[r, c] else 0
    return arr


def board_image(path, side):
    return Image.open(path).convert("RGB").resize((side, side), Image.LANCZOS)


def compose(source_path, index, width, height):
    arr = np.full((height, width, 3), GRAY, dtype=np.uint8)
    top = (height - width) // 2
    arr[top:top + width] = np.asarray(board_image(source_path, width))
    return draw_nonce(arr, index, width, height)


def play_order(manifest_path):
    """[(source_index, png_path)] in play order: frames by index, interruptions inserted after
    their playAfterFrameIndex. The source index is the number in the file name."""
    with open(manifest_path) as f:
        m = json.load(f)
    pixels = os.path.join(os.path.dirname(os.path.abspath(manifest_path)), "pixels")
    inter = m.get("interruptions") or ([m["interruption"]] if m.get("interruption") else [])
    after = {}
    for it in inter:
        after.setdefault(it["playAfterFrameIndex"], []).append(it["file"])

    def entry(name):
        return int(re.search(r"(\d+)", name).group(1)), os.path.join(pixels, name)

    order = []
    for fr in sorted(m["frames"], key=lambda x: x["index"]):
        order.append(entry(fr["file"]))
        order += [entry(n) for n in after.get(fr["index"], [])]
    return order


def encoder_args(encoder, crf):
    if encoder == "libx265":
        return ["-c:v", "libx265", "-preset", "medium", "-crf", str(crf),
                "-x265-params", "keyint=60:min-keyint=60:pools=2:frame-threads=1:log-level=error:"
                "colorprim=bt709:transfer=bt709:colormatrix=bt709:range=limited"]
    if encoder == "hevc_videotoolbox":
        return ["-c:v", "hevc_videotoolbox", "-q:v", "65", "-g", "60"]
    raise ValueError(encoder)


def encode(composites, holds, out_path, width, height, fps=30, encoder="libx265", crf=20):
    """composites: list of HxWx3 uint8 arrays; holds: frames per composite."""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps),
           "-i", "-", "-an",
           "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
           *encoder_args(encoder, crf),
           "-pix_fmt", "yuv420p", "-tag:v", "hvc1",
           "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709",
           "-color_trc", "bt709",
           "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
           "-movflags", "+faststart", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for comp, n in zip(composites, holds):
            data = np.ascontiguousarray(comp).tobytes()
            for _ in range(n):
                proc.stdin.write(data)
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg encode failed")


REPLAY_MANIFEST = "/Users/alexmunzon/chess-builds/replay-sequence-2026-11-15/sequence/replay-manifest.json"
SPECIAL_MANIFEST = "/Users/alexmunzon/chess-builds/special-game-2026-11-15/sequence/replay-manifest.json"


def build_all(outdir, extra):
    """Build the standard set: both games at 720x1280 and at 504x896."""
    os.makedirs(outdir, exist_ok=True)
    jobs = [(REPLAY_MANIFEST, "replay-14.mp4", "720x1280"), (SPECIAL_MANIFEST, "special-game.mp4", "720x1280"),
            (REPLAY_MANIFEST, "replay-14-504x896.mp4", "504x896"),
            (SPECIAL_MANIFEST, "special-game-504x896.mp4", "504x896")]
    for manifest, name, size in jobs:
        main([manifest, os.path.join(outdir, name), "--size", size, *extra])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--all"]:
        return build_all(argv[1], argv[2:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest")
    ap.add_argument("out")
    ap.add_argument("--size", default="720x1280", choices=["720x1280", "504x896"])
    ap.add_argument("--hold", type=float, default=2.0, help="seconds each source frame is shown")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--encoder", default="libx265", choices=["libx265", "hevc_videotoolbox"])
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--save-composites", help="directory to write the composited PNGs into")
    a = ap.parse_args(argv)
    width, height = map(int, a.size.split("x"))
    per = round(a.hold * a.fps)
    if per < 1 or abs(per - a.hold * a.fps) > 1e-6:
        sys.exit("hold * fps must be a whole number of frames")
    order = play_order(a.manifest)
    comps = [compose(p, idx, width, height) for idx, p in order]
    if a.save_composites:
        os.makedirs(a.save_composites, exist_ok=True)
        for slot, ((idx, _), c) in enumerate(zip(order, comps)):
            Image.fromarray(c).save(os.path.join(a.save_composites, f"slot-{slot:03d}-src-{idx:03d}.png"))
    encode(comps, [per] * len(comps), a.out, width, height, a.fps, a.encoder, a.crf)
    with open(a.out, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    print(json.dumps({"out": a.out, "size": a.size, "fps": a.fps, "holdSeconds": a.hold,
                      "encoder": a.encoder, "slots": len(order),
                      "playOrder": [i for i, _ in order], "frames": per * len(order),
                      "sha256": digest}))


if __name__ == "__main__":
    main()
