#!/usr/bin/env python3
"""Opt-in checks for the mock-glasses video nonce and verifier (needs ffmpeg + external frames).

  python3 -B tests/mock_glasses_video.py

Skips (exit 0, prints SKIP) when ffmpeg or the synthetic input frames are missing.
Positive controls: clean composites decode to their index; a short correctly ordered video
verifies. Negative checks: blurred nonce band, 50/50 blend of two consecutive frames, a
corrupted CRC bit, a top/bottom copy mismatch and a wrong-order video must all be rejected.
"""
import importlib.util
import os
import sys
import tempfile

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM = os.path.join(ROOT, "scripts", "simulation")


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SIM, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mk = load("mockvid", "make-mock-glasses-video.py")
vf = load("mockverify", "verify-mock-glasses-video.py")

failures = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def blur_bands(frame, radius):
    img = Image.fromarray(frame)
    w, h = img.size
    band = (h - w) // 2
    for box in ((0, 0, w, band), (0, h - band, w, h)):
        img.paste(img.crop(box).filter(ImageFilter.GaussianBlur(radius)), box)
    return np.asarray(img)


def flip_pair(frame, pair_index, which_bands=(0, 1)):
    """Swap the two blocks of one Manchester pair (still a valid pair, wrong bit)."""
    out = frame.copy()
    h, w = out.shape[:2]
    lay = mk.layout(w, h)
    b = lay["block"]
    row, col = 1 + pair_index // 8, (pair_index % 8) * 2
    for bi in which_bands:
        y1, y2 = round(lay["band_y"][bi] + row * b), round(lay["band_y"][bi] + (row + 1) * b)
        xa, xb, xc = (round(lay["grid_x"] + k * b) for k in (col, col + 1, col + 2))
        left = out[y1:y2, xa:xb].copy()
        out[y1:y2, xa:xb] = out[y1:y2, xb:xc]
        out[y1:y2, xb:xc] = left
    return out


def main():
    manifest = mk.REPLAY_MANIFEST
    if not os.path.exists(mk.FFMPEG) or not os.path.exists(manifest):
        print(f"SKIP: needs {mk.FFMPEG} and {manifest}")
        return 0
    order = mk.play_order(manifest)
    W, H = 720, 1280

    # positive controls on composites, at full size and after a downscale to 360x640
    comps = {i: mk.compose(p, i, W, H) for i, p in order[:6]}
    for i, c in comps.items():
        small = np.asarray(Image.fromarray(c).resize((360, 640), Image.BILINEAR))
        check(f"clean composite {i} decodes", vf.read_nonce(c)["index"] == i
              and vf.read_nonce(small)["index"] == i)
    check("all 256 codes round-trip and are distinct",
          all(vf.decode_grid(mk.nonce_pattern(k).astype(np.int8))[0] == k for k in range(256)))

    # 1. heavy blur of the nonce band -> abstain, never a different index
    for radius in (25, 40):
        r = vf.read_nonce(blur_bands(comps[4], radius))
        check(f"heavily blurred band (radius {radius}) rejected", r["index"] is None, r["reason"])
    sweep = [(i, rad, vf.read_nonce(blur_bands(comps[i], rad))["index"])
             for i in comps for rad in (2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 30)]
    wrong = [(i, rad, got) for i, rad, got in sweep if got is not None and got != i]
    check("blur sweep radius 2-30: never a wrong index", not wrong,
          f"{sum(g is None for *_, g in sweep)} abstained, {sum(g == i for i, _, g in sweep)} correct, {len(wrong)} wrong")

    # 2. 50/50 blend of two consecutive source frames -> rejected
    for a, b in ((2, 3), (4, 5), (0, 5)):
        mix = ((comps[a].astype(np.uint16) + comps[b]) // 2).astype(np.uint8)
        r = vf.read_nonce(mix)
        check(f"50/50 blend of frames {a}+{b} rejected", r["index"] is None, r["reason"])

    # 3. corrupted checksum bit (pair 15 is the last CRC bit) and a corrupted data bit
    for pair in (15, 8, 3):
        r = vf.read_nonce(flip_pair(comps[4], pair))
        check(f"flipped bit {pair} in both copies rejected", r["index"] is None, r["reason"])
    r = vf.read_nonce(flip_pair(comps[4], 15, which_bands=(1,)))
    check("bottom copy alone corrupted rejected", r["index"] is None, r["reason"])

    # half-updated frame: top band from frame 5, rest from frame 4
    torn = comps[4].copy()
    torn[:H // 2] = comps[5][:H // 2]
    r = vf.read_nonce(torn)
    check("torn frame (top half new, bottom half old) rejected", r["index"] is None, r["reason"])

    # 4. short real videos: correct order passes, swapped order fails
    with tempfile.TemporaryDirectory() as d:
        sub_manifest = os.path.join(d, "replay-manifest.json")
        os.symlink(os.path.dirname(manifest) + "/pixels", os.path.join(d, "pixels"))
        import json
        with open(manifest) as f:
            m = json.load(f)
        m["frames"] = [fr for fr in m["frames"] if fr["index"] < 4]
        m.pop("interruption", None)
        with open(sub_manifest, "w") as f:
            json.dump(m, f)
        sub = mk.play_order(sub_manifest)
        hold, fps = 0.5, 30
        per = int(hold * fps)
        good = os.path.join(d, "good.mp4")
        mk.encode([mk.compose(p, i, W, H) for i, p in sub], [per] * len(sub), good, W, H, fps)
        rep = vf.verify(good, sub_manifest, hold=hold)
        check("short correctly ordered video passes", rep["pass"], f"{rep['decodedFrames']} frames")
        swapped = [sub[0], sub[2], sub[1], sub[3]]   # frames 1 and 2 differ in pixels and index
        bad = os.path.join(d, "swapped.mp4")
        mk.encode([mk.compose(p, i, W, H) for i, p in swapped], [per] * 4, bad, W, H, fps)
        rep = vf.verify(bad, sub_manifest, hold=hold)
        check("wrong-order video fails verification", not rep["pass"],
              f"{rep['failureCount']} failing frames")
        # pixels swapped but nonces left in order: board check alone must catch it
        lying = os.path.join(d, "lying.mp4")
        mk.encode([mk.compose(swapped[k][1], sub[k][0], W, H) for k in range(4)], [per] * 4, lying, W, H, fps)
        rep = vf.verify(lying, sub_manifest, hold=hold)
        check("right nonces on wrong boards fails verification", not rep["pass"],
              f"{rep['failureCount']} failing frames")

    print(f"{'PASS' if not failures else 'FAIL'}: {len(failures)} failing checks")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
