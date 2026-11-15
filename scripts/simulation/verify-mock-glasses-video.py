#!/usr/bin/env python3
"""Verify a mock-glasses video frame by frame against its source manifest.

  verify-mock-glasses-video.py VIDEO MANIFEST [--hold 2.0] [--downscale 360x640]
      [--mae-bound 6.0] [--json OUT.json] [--avfoundation]

Every decoded frame (ffmpeg pipes raw RGB to python) must:
  * carry a valid nonce (both copies decode, CRC passes, copies agree), equal to the source
    index expected for its time slot (frame n -> slot floor(n / (fps * hold)));
  * have a board region within --mae-bound mean absolute error (0-255 scale) of the expected
    source PNG scaled to the decoded board size, and be nearer to it than to any other
    distinct source image: its count of strongly differing pixels (> BIG_DIFF) against the
    expected source must be under half that against every other close source (and that other
    count must exceed MIN_DISTINCT_PIXELS).
Frames at hold boundaries (first and last frame of each slot) are reported separately.
--downscale scales frames during decode (bilinear), simulating the smallest 360x640 stream.
--avfoundation also opens the file with Apple's AVFoundation (small Swift script) and reports
track format and decoded frame count. Exit code 0 = PASS, 1 = FAIL.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("mockvid", os.path.join(HERE, "make-mock-glasses-video.py"))
mk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mk)

FFPROBE = os.environ.get("FFPROBE", "/usr/local/bin/ffprobe")
BLACK_MAX, WHITE_MIN = 80.0, 175.0
BIG_DIFF = 48          # a pixel "strongly differs" when some channel is off by more than this
MIN_DISTINCT_PIXELS = 50


def luma(arr):
    a = arr.astype(np.float32)
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def read_grid(gray, y0, lay):
    """Return (4x16 array of 0/1/-1, min margin). -1 = ambiguous block."""
    b = lay["block"]
    out = np.full((mk.ROWS, mk.COLS), -1, dtype=np.int8)
    margin = 255.0
    for r in range(mk.ROWS):
        for c in range(mk.COLS):
            x1 = int(round(lay["grid_x"] + (c + 0.25) * b))
            x2 = int(round(lay["grid_x"] + (c + 0.75) * b))
            y1 = int(round(y0 + (r + 0.25) * b))
            y2 = int(round(y0 + (r + 0.75) * b))
            v = float(gray[y1:max(y2, y1 + 1), x1:max(x2, x1 + 1)].mean())
            if v <= BLACK_MAX:
                out[r, c] = 0
                margin = min(margin, BLACK_MAX - v)
            elif v >= WHITE_MIN:
                out[r, c] = 1
                margin = min(margin, v - WHITE_MIN)
            else:
                margin = min(margin, -min(v - BLACK_MAX, WHITE_MIN - v))
    return out, margin


def decode_grid(grid):
    """Return (index or None, reason)."""
    if (grid < 0).any():
        return None, "ambiguous-block"
    ref = mk.nonce_pattern(0)
    if not (np.array_equal(grid[0], ref[0]) and np.array_equal(grid[3], ref[3])):
        return None, "bad-start-stop"
    blocks = list(grid[1]) + list(grid[2])
    bits = []
    for i in range(0, 32, 2):
        pair = (blocks[i], blocks[i + 1])
        if pair == (0, 1):
            bits.append(1)
        elif pair == (1, 0):
            bits.append(0)
        else:
            return None, "bad-manchester-pair"
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    index, check = value >> 8, value & 0xFF
    if mk.crc8(index) != check:
        return None, "bad-crc"
    return index, "ok"


def read_nonce(frame):
    """frame: HxWx3 uint8. Returns dict(index or None, reason, margin)."""
    h, w = frame.shape[:2]
    lay = mk.layout(w, h)
    gray = luma(frame)
    results, margin = [], 255.0
    for y0 in lay["band_y"]:
        grid, m = read_grid(gray, y0, lay)
        margin = min(margin, m)
        results.append(decode_grid(grid))
    (a, ra), (b, rb) = results
    if a is None or b is None:
        return {"index": None, "reason": f"top:{ra},bottom:{rb}", "margin": margin}
    if a != b:
        return {"index": None, "reason": "copies-disagree", "margin": margin}
    return {"index": a, "reason": "ok", "margin": margin}


def mp4_tracks(video):
    """Walk the MP4 boxes: per track handler type, sample-entry fourcc, sample count, size."""
    with open(video, "rb") as f:
        data = f.read()

    def boxes(start, end):
        i = start
        while i + 8 <= end:
            size = int.from_bytes(data[i:i + 4], "big")
            kind = data[i + 4:i + 8].decode("latin-1")
            hdr = 8
            if size == 1:
                size, hdr = int.from_bytes(data[i + 8:i + 16], "big"), 16
            elif size == 0:
                size = end - i
            if size < hdr:
                return
            yield kind, i + hdr, i + size
            i += size

    def find(start, end, path):
        for kind, s, e in boxes(start, end):
            if kind == path[0]:
                return (s, e) if len(path) == 1 else find(s, e, path[1:])
        return None

    moov = find(0, len(data), ["moov"])
    tracks = []
    for kind, s, e in boxes(*moov):
        if kind != "trak":
            continue
        hdlr = find(s, e, ["mdia", "hdlr"])
        stsd = find(s, e, ["mdia", "minf", "stbl", "stsd"])
        stsz = find(s, e, ["mdia", "minf", "stbl", "stsz"])
        entry = data[stsd[0] + 8 + 4:stsd[0] + 8 + 8].decode("latin-1") if stsd else None
        w = h = None
        if stsd and entry:
            body = stsd[0] + 8 + 8  # sample entry payload
            w = int.from_bytes(data[body + 24:body + 26], "big")
            h = int.from_bytes(data[body + 26:body + 28], "big")
        tracks.append({"handler": data[hdlr[0] + 8:hdlr[0] + 12].decode("latin-1") if hdlr else None,
                       "fourcc": entry, "width": w, "height": h,
                       "samples": int.from_bytes(data[stsz[0] + 8:stsz[0] + 12], "big") if stsz else None})
    return tracks


def probe(video):
    """ffprobe when installed; otherwise ffmpeg's stream banner plus our own MP4 box walk."""
    if os.path.exists(FFPROBE):
        out = subprocess.run([FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", video],
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)
    banner = subprocess.run([mk.FFMPEG, "-hide_banner", "-i", video], capture_output=True, text=True).stderr
    streams = []
    for t in mp4_tracks(video):
        if t["handler"] == "vide":
            m = re.search(r"Video: (\w+).*?\((\w{4}) / 0x[0-9a-f]+\), (\w+)\(.*?\b(\d+)x(\d+)\b.*?([\d.]+) fps", banner)
            streams.append({"codec_type": "video", "codec_name": m.group(1), "codec_tag_string": t["fourcc"],
                            "bannerTag": m.group(2), "pix_fmt": m.group(3), "width": int(m.group(4)),
                            "height": int(m.group(5)), "r_frame_rate": f"{m.group(6)}/1",
                            "nb_frames": t["samples"]})
        else:
            streams.append({"codec_type": {"soun": "audio"}.get(t["handler"], t["handler"]),
                            "codec_tag_string": t["fourcc"]})
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", banner)
    seconds = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))
    return {"streams": streams, "format": {"duration": seconds}, "source": "ffmpeg-banner+mp4-boxes",
            "banner": [ln.strip() for ln in banner.splitlines() if "Stream #" in ln or "Duration" in ln]}


def iter_frames(video, width, height):
    cmd = [mk.FFMPEG, "-hide_banner", "-loglevel", "error", "-i", video, "-an",
           "-vf", f"scale={width}:{height}:flags=bilinear:in_color_matrix=bt709:in_range=tv",
           "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = width * height * 3
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def board_crop(frame):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = mk.layout(w, h)["board"]
    return frame[int(round(y1)):int(round(y2)), int(round(x1)):int(round(x2))]


def verify(video, manifest, hold=2.0, downscale=None, mae_bound=6.0, frames=None):
    """Returns a report dict; report['pass'] is the verdict. `frames` may override decoding."""
    info = probe(video)
    vs = [s for s in info["streams"] if s["codec_type"] == "video"]
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    v = vs[0]
    num, den = map(int, v["r_frame_rate"].split("/"))
    fps = num / den
    width, height = (map(int, downscale.split("x")) if downscale else (v["width"], v["height"]))
    order = mk.play_order(manifest)
    per = round(fps * hold)
    side = int(round(mk.layout(width, height)["board"][2]))
    native = int(v["width"])
    # expected boards at decoded size (same path as the stream: native board, then bilinear
    # downscale), plus small copies for the coarse nearest-source screen
    paths = sorted({p for _, p in order})

    def ref_board(p):
        img = mk.board_image(p, native)
        return img if side == native else img.resize((side, side), Image.BILINEAR)
    refs = {p: np.asarray(ref_board(p)).astype(np.int16) for p in paths}
    small = {p: np.asarray(Image.fromarray(refs[p].astype(np.uint8)).resize((96, 96), Image.BOX)).astype(np.float32)
             for p in paths}
    digest = {}  # byte-identical sources (e.g. replay frames 0 and 1) count as the same image
    for p in paths:
        with open(p, "rb") as f:
            digest[p] = hashlib.sha256(f.read()).hexdigest()
    report = {"video": video, "manifest": manifest, "decodedSize": f"{width}x{height}", "fps": fps,
              "holdSeconds": hold, "codec": v.get("codec_name"), "tag": v.get("codec_tag_string"),
              "pixFmt": v.get("pix_fmt"), "audioStreams": len(audio), "maeBound": mae_bound,
              "slots": len(order), "expectedFrames": per * len(order)}
    stats = {"interior": {"n": 0, "maxMae": 0.0, "minMargin": 255.0},
             "boundary": {"n": 0, "maxMae": 0.0, "minMargin": 255.0}}
    failures = []
    n = -1
    source = frames if frames is not None else iter_frames(video, width, height)
    for n, fr in enumerate(source):
        slot = n // per
        kind = "boundary" if n % per in (0, per - 1) else "interior"
        problems = []
        if slot >= len(order):
            failures.append({"frame": n, "problems": ["extra-frame"]})
            continue
        exp_idx, exp_path = order[slot]
        nonce = read_nonce(fr)
        if nonce["index"] is None:
            problems.append(f"nonce-invalid({nonce['reason']})")
        elif nonce["index"] != exp_idx:
            problems.append(f"nonce {nonce['index']} != expected {exp_idx}")
        board = board_crop(fr)
        mae = float(np.abs(board.astype(np.int16) - refs[exp_path]).mean())
        if mae > mae_bound:
            problems.append(f"board-mae {mae:.2f} > {mae_bound}")
        bs = np.asarray(Image.fromarray(np.ascontiguousarray(board)).resize((96, 96), Image.BOX)).astype(np.float32)
        coarse = {p: float(np.abs(bs - small[p]).mean()) for p in paths}
        # Consecutive positions differ by one or two pieces (global MAE only ~0.1-0.3), so the
        # identity test counts strongly differing pixels (any channel off by > BIG_DIFF).
        # Coarse 96x96 screen first, then the full-resolution count for close candidates.
        close = [p for p in paths if digest[p] != digest[exp_path] and coarse[p] <= coarse[exp_path] + 5.0]
        b16 = board.astype(np.int16)
        own = int((np.abs(b16 - refs[exp_path]).max(axis=2) > BIG_DIFF).sum())
        st = stats[kind]
        st["maxOwnBigPixels"] = max(st.get("maxOwnBigPixels", 0), own)
        if close:
            other = min(int((np.abs(b16 - refs[p]).max(axis=2) > BIG_DIFF).sum()) for p in close)
            st["minOtherBigPixels"] = min(st.get("minOtherBigPixels", 10 ** 9), other)
            if other <= max(2 * own, MIN_DISTINCT_PIXELS):
                problems.append(f"board not clearly its source (own {own} vs other {other} differing px)")
        # with no close candidate, every other distinct source is > 5 coarse units further away
        st["n"] += 1
        st["maxMae"] = max(st["maxMae"], mae)
        st["minMargin"] = min(st["minMargin"], nonce["margin"])
        if problems:
            failures.append({"frame": n, "slot": slot, "kind": kind, "problems": problems})
    decoded = n + 1
    report.update({"decodedFrames": decoded, "interior": stats["interior"], "boundary": stats["boundary"],
                   "failures": failures[:20], "failureCount": len(failures)})
    fmt_ok = (v.get("codec_name") == "hevc" and v.get("codec_tag_string") == "hvc1"
              and v.get("pix_fmt") == "yuv420p" and not audio)
    report["formatOk"] = fmt_ok
    report["pass"] = bool(fmt_ok and not failures and decoded == per * len(order))
    return report


SWIFT_SRC = r'''
import AVFoundation
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let asset = AVURLAsset(url: url)
let sem = DispatchSemaphore(value: 0)
Task {
  do {
    let tracks = try await asset.loadTracks(withMediaType: .video)
    let audio = try await asset.loadTracks(withMediaType: .audio)
    guard let t = tracks.first else { print("NO_VIDEO_TRACK"); exit(1) }
    let fds = try await t.load(.formatDescriptions)
    let sub = CMFormatDescriptionGetMediaSubType(fds[0])
    let fourcc = String(bytes: [24, 16, 8, 0].map { UInt8((sub >> $0) & 0xff) }, encoding: .ascii) ?? "?"
    let size = try await t.load(.naturalSize)
    let fps = try await t.load(.nominalFrameRate)
    let dur = try await asset.load(.duration)
    let reader = try AVAssetReader(asset: asset)
    let out = AVAssetReaderTrackOutput(track: t, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange])
    reader.add(out)
    reader.startReading()
    var n = 0
    while let sb = out.copyNextSampleBuffer() { if CMSampleBufferGetImageBuffer(sb) != nil { n += 1 } }
    print("{\"fourcc\":\"\(fourcc)\",\"width\":\(Int(size.width)),\"height\":\(Int(size.height)),\"fps\":\(fps),\"seconds\":\(CMTimeGetSeconds(dur)),\"videoTracks\":\(tracks.count),\"audioTracks\":\(audio.count),\"decodedFrames\":\(n),\"readerStatus\":\(reader.status.rawValue)}")
  } catch { print("ERROR \(error)"); exit(1) }
  sem.signal()
}
sem.wait()
'''


def avfoundation_check(video):
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "avcheck.swift")
        with open(src, "w") as f:
            f.write(SWIFT_SRC)
        binp = os.path.join(d, "avcheck")
        subprocess.run(["swiftc", "-O", "-module-cache-path", os.path.join(d, "mc"), src, "-o", binp],
                       check=True, capture_output=True)
        out = subprocess.run([binp, video], capture_output=True, text=True)
    line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr.strip()
    try:
        return json.loads(line)
    except ValueError:
        return {"error": line}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("manifest")
    ap.add_argument("--hold", type=float, default=2.0)
    ap.add_argument("--downscale")
    ap.add_argument("--mae-bound", type=float, default=6.0)
    ap.add_argument("--json")
    ap.add_argument("--avfoundation", action="store_true")
    a = ap.parse_args(argv)
    rep = verify(a.video, a.manifest, a.hold, a.downscale, a.mae_bound)
    if a.avfoundation:
        av = avfoundation_check(a.video)
        rep["avfoundation"] = av
        av_ok = (av.get("fourcc") == "hvc1" and av.get("decodedFrames") == rep["decodedFrames"]
                 and av.get("audioTracks") == 0 and av.get("readerStatus") == 2)
        rep["avfoundationOk"] = av_ok
        rep["pass"] = rep["pass"] and av_ok
    if a.json:
        with open(a.json, "w") as f:
            json.dump(rep, f, indent=2)
    i, b = rep["interior"], rep["boundary"]
    print(f"{os.path.basename(a.video)} @ {rep['decodedSize']}: {rep['decodedFrames']}/{rep['expectedFrames']} frames, "
          f"{rep['slots']} slots, codec={rep['codec']} tag={rep['tag']} audio={rep['audioStreams']}")
    for name, s in (("interior", i), ("boundary", b)):
        print(f"  {name} n={s['n']} maxMAE={s['maxMae']:.2f} minNonceMargin={s['minMargin']:.1f} "
              f"bigDiffPx own<={s.get('maxOwnBigPixels')} nearestOther>={s.get('minOtherBigPixels')}")
    if "avfoundation" in rep:
        print(f"  avfoundation: {json.dumps(rep['avfoundation'])}")
    for fail in rep["failures"]:
        print("  FAIL", fail)
    print(("PASS" if rep["pass"] else "FAIL") + f" (failures={rep['failureCount']}, MAE bound {rep['maeBound']})")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
