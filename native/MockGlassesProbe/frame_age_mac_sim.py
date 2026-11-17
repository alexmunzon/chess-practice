#!/usr/bin/env python3
"""Method 1 (on-screen code) frame-age study on the Mac: simulated video only, no Simulator, no Meta code.

usage: frame_age_mac_sim.py --out OUT.json [--video replay-14.mp4 | --synthetic] [--epochs 24] [--seed 1]
                            [--display-log-lag SECONDS] [--records RECORDS.json]

Why: the Simulator harness (FrameAgeHarness.swift) modelled its display log from wall-clock callbacks, and that
log was up to 0.23 s later than pictures that already showed the code, more than the 0.05 s margin under test.
Here every time comes from a frame counter on one virtual clock:
- display: in each stream, frame d of the pinned test video (looped every 30 s) is on screen from start + d/30. The
  display log records each code at the first display frame that shows it, plus --display-log-lag (default 0; a
  non-zero lag reproduces the old harness fault on purpose).
- camera: picture i exposes from S_i for 8, 33 or 100 ms (cycled per stream), S_i = start + phase + i/30*(1+drift).
  A picture whose exposure spans a code change is a pixel blend of the two video frames, read with the project's
  reader (--synthetic: a code is read only when it covers >= 90% of the exposure).
- delivery: received 30-120 ms after the exposure ends, then the scenario of its 3 s segment applies.
Truth: age = judge time - the moment the shown content was on screen (exposure start; for a replayed screen, the
moment the replayed content was on the real display). Stale = age > nonceMaxAge. Every picture is scored, including
those after the video loops (codes repeat) and holds longer than the 30 s code cycle.

Scenarios. Controls the rule is built to handle (old accepted should be 0 when exposure <= margin): fresh, isolated
holds 0.1-10 s, queues, bursts, drops, repeated copies, long holds 30-60 s. Weakness probes, which break an
assumption of the rule on purpose (a non-zero count is a finding about the method, not a harness bug): a second
screen replaying the display 2, 5 or 20 s late or from the previous stream; the reader returning the neighbouring
valid code (+1 newer, -1 older); exposure of 100 ms (longer than the 50 ms margin).

Self-check before scoring: the display log is compared with the true first display time of each code, computed
separately from the video's code track. If they differ by more than the margin, nothing is scored (exit 3).
The rule is judged with analyze_frame_age.nonce_evaluate, a port of NonceAgeGate checked against the Swift rule.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import random
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FPS = 30
CODES, SLOT_FRAMES, FILE_FRAMES = 15, 60, 900
EXPOSURES = [0.008, 0.033, 0.100]
LATENCY = (0.03, 0.12)
MAX_AGE, MARGIN = 3.0, 0.05          # rule settings; must equal FrameAgeConfig in FrameAgeHarness.swift
EPOCH_SECONDS = 100.0
DELAYS = [0.1, 0.2, 0.3, 0.45, 0.55, 0.95, 1.05, 2.0, 2.5, 2.8, 2.85, 2.9, 2.95, 3.0, 3.05, 3.1, 3.2, 5.0, 10.0]
LONG_HOLDS = [30.0, 32.0, 45.0, 60.0]
QUEUES = [0.2, 0.5, 1.2, 2.9, 3.1]
REPLAY = [2.0, 5.0, 20.0, "previous-stream"]
SEGMENTS = ["fresh", "isolated", "sustained", "fresh", "burst", "fresh", "drop", "repeat", "long-hold", "replay", "misread"]
CONTROLS = {"fresh", "isolated", "sustained", "burst", "drop", "repeat", "long-hold"}
SEGMENT_FRAMES = 90
VIDEO_SHA256 = "cf99c6661507c5de71fb931e2abfff1d2c4109a5520cd8e9202604bf2f3b8e87"
DEFAULT_VIDEO = "/Users/alexmunzon/chess-builds/mock-glasses-2026-11-15/phase2/replay-14.mp4"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


nonce_evaluate = load("analyze_frame_age", os.path.join(HERE, "analyze_frame_age.py")).nonce_evaluate


class SyntheticVideo:
    """Codes by frame count (frame k shows code k // 60); a blend reads a code only when it covers >= 90%."""
    codes = [(k // SLOT_FRAMES) % CODES for k in range(FILE_FRAMES)]
    cache = {}

    def blend(self, k0, k1, w):
        return self.codes[k1] if w >= 0.9 else self.codes[k0] if w <= 0.1 else None


class DecodedVideo:
    """The pinned test video decoded with ffmpeg and read with the project's reader (verify-mock-glasses-video.py)."""
    def __init__(self, path):
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        if digest != VIDEO_SHA256:
            sys.exit(f"video hash {digest} is not the pinned test video")
        sim = os.path.join(ROOT, "scripts", "simulation")
        sys.modules["mockvid"] = load("mockvid", os.path.join(sim, "make-mock-glasses-video.py"))
        self.vf = load("mockverify", os.path.join(sim, "verify-mock-glasses-video.py"))
        # Streamed: only frames next to a code change are kept (for blends), plus the first and last (loop seam).
        self.codes, self.frames, prev = [], {}, None
        for k, frame in enumerate(self.vf.iter_frames(path, 720, 1280)):
            code = self.vf.read_nonce(frame)["index"]
            if k == 0 or (self.codes and code != self.codes[-1]):
                self.frames[k] = frame.copy()
                if prev is not None:
                    self.frames[k - 1] = prev
            self.codes.append(code)
            prev = frame.copy()
        if len(self.codes) != FILE_FRAMES:
            sys.exit(f"expected {FILE_FRAMES} frames, decoded {len(self.codes)}")
        self.frames[FILE_FRAMES - 1] = prev
        self.cache = {}

    def blend(self, k0, k1, w):
        w = round(w, 2)
        key = (k0, k1, w)
        if key not in self.cache:
            import numpy as np
            mix = (1 - w) * self.frames[k0].astype(np.float32) + w * self.frames[k1].astype(np.float32)
            self.cache[key] = self.vf.read_nonce(np.clip(mix + 0.5, 0, 255).astype(np.uint8))["index"]
        return self.cache[key]


def read_picture(video, stream_start, s, exposure):
    """Code read from a picture exposed over [s, s + exposure] of a display that started at stream_start.
    Returns (code, display frame at exposure start). An exposure spans at most one code change (<= 0.1 s << 2 s)."""
    d0 = int(math.floor((s - stream_start) * FPS))
    d1 = int(math.floor((s + exposure - stream_start) * FPS - 1e-9))
    codes = [video.codes[d % FILE_FRAMES] for d in range(d0, d1 + 1)]
    if all(c == codes[0] for c in codes):
        return codes[0], d0
    dc = next(d for d in range(d0 + 1, d1 + 1) if video.codes[d % FILE_FRAMES] != codes[0])
    w = (s + exposure - (stream_start + dc / FPS)) / exposure
    return video.blend((dc - 1) % FILE_FRAMES, dc % FILE_FRAMES, w), d0


def true_first_display(video):
    """Independent of the display log: first video frame index of each code (all 15 appear in one loop)."""
    return {c: video.codes.index(c) / FPS for c in set(video.codes) if c is not None}


def simulate(video, epochs, seed, lag):
    rng = random.Random(seed)
    records, clock_error, lateness = [], [], defaultdict(list)
    delay_i = long_i = replay_i = misread_i = 0
    period = EPOCH_SECONDS + 1.0
    start = 1000.0
    truth_first = true_first_display(video)
    for e in range(1, epochs + 1):
        next_start = start + period
        exposure = EXPOSURES[(e - 1) % len(EXPOSURES)]
        # Display log from the frame counter (first display frame that shows each code), plus the injected lag.
        log = {}
        for d in range(int(EPOCH_SECONDS * FPS)):
            c = video.codes[d % FILE_FRAMES]
            if c is not None and c not in log:
                log[c] = start + d / FPS + lag
        clock_error += [log[c] - (start + truth_first[c]) for c in log]
        phase, drift = rng.uniform(0, 1 / FPS), rng.uniform(-0.0015, 0.0015)
        seg_param = {}
        for i in range(int((EPOCH_SECONDS - 0.2) * FPS)):
            s = start + phase + i / FPS * (1 + drift)
            seg = i // SEGMENT_FRAMES
            kind = "fresh" if seg == 0 else SEGMENTS[(seg + e) % len(SEGMENTS)]   # rotated so every kind meets the first loop
            if seg not in seg_param:
                seg_param[seg] = {"queue": rng.choice(QUEUES), "burst": rng.uniform(0.2, 3.5),
                                  "drop": rng.choice([0.2, 0.4, 1.0, 3.0])}
            p = seg_param[seg]
            j = i % SEGMENT_FRAMES
            content, label = s, kind
            if kind == "replay":
                r = REPLAY[replay_i % len(REPLAY)]; replay_i += 1
                content = s - (period if r == "previous-stream" else r)
                label = f"replay-{r}" if r == "previous-stream" else f"replay-{r:g}s"
            src_start = start if content >= start else start - period   # the previous stream ran the same video
            code, d0 = read_picture(video, src_start, content, exposure)
            true_code = code
            if kind == "misread" and code is not None:
                step = 1 if misread_i % 2 == 0 else -1; misread_i += 1
                code = (code + step) % CODES
                label = f"misread{step:+d}"
            if kind in CONTROLS and code is not None and code in log:
                lateness[exposure].append(log[code] - s)
            receipt = s + exposure + rng.uniform(*LATENCY)
            copies = []                      # (judge time, mode)
            if kind == "isolated":
                if j % 3 == 2:
                    copies.append((receipt + DELAYS[delay_i % len(DELAYS)], "held")); delay_i += 1
                else:
                    copies.append((receipt, "fresh"))
            elif kind == "long-hold":
                if j % 3 == 2:
                    copies.append((receipt + LONG_HOLDS[long_i % len(LONG_HOLDS)], "held")); long_i += 1
                else:
                    copies.append((receipt, "fresh"))
            elif kind == "sustained":
                label = f"queue-{p['queue']}"
                copies.append((receipt + p["queue"], "held"))
            elif kind == "burst":
                copies.append((max(receipt, start + phase + (seg + 1) * SEGMENT_FRAMES / FPS + p["burst"]), "held"))
            elif kind == "drop":
                if j / FPS >= p["drop"]:
                    copies.append((receipt, "fresh"))
            elif kind == "repeat":
                copies.append((receipt, "fresh"))
                if j % 4 == 3:
                    copies.append((receipt + DELAYS[delay_i % len(DELAYS)], "held")); delay_i += 1
            elif kind in ("replay", "misread"):
                copies.append((receipt, "fresh"))
                if j % 3 == 2:
                    copies.append((receipt + DELAYS[delay_i % len(DELAYS)], "held")); delay_i += 1
            else:
                copies.append((receipt, "fresh"))
            for now, mode in copies:
                gate_epoch = e if now < next_start else e + 1 + int((now - next_start) // period)
                first = lambda c, t, lg=log: lg[c] if c in lg and lg[c] <= t else None
                ok, why, bound = nonce_evaluate(first, code, e, gate_epoch, now, MAX_AGE, MARGIN)
                records.append({"epoch": e, "label": label, "mode": mode, "exposure": exposure, "capture": s,
                                "exposureEnd": s + exposure, "receipt": receipt, "judge": now, "content": content,
                                "afterLoop": d0 >= FILE_FRAMES, "code": code, "trueCode": true_code,
                                "age": now - content, "accept": ok, "reason": why, "bound": bound})
        start = next_start
    return records, clock_error, lateness


def frac(n, m):
    return f"{n} of {m}"


def summarise(records, clock_error, lateness, lag, seed, epochs, source):
    max_err = max(abs(x) for x in clock_error)
    out = {"simulatedVideoOnTheMac": True, "source": source, "seed": seed, "epochs": epochs, "displayLogLag": lag,
           "maxAge": MAX_AGE, "margin": MARGIN, "exposures": EXPOSURES, "latency": LATENCY,
           "epochSeconds": EPOCH_SECONDS,
           "harnessTiming": {"displayLogVsTrueDisplayMaxMs": round(1000 * max_err, 3),
                             "codesCompared": len(clock_error),
                             "codesOffByMoreThanMargin": frac(sum(abs(x) > MARGIN for x in clock_error), len(clock_error))},
           "scored": max_err <= MARGIN}
    # Physical effect, not harness error: how much later the log is than the exposure start of a picture showing it.
    out["pictureBeforeLogMaxMs"] = {f"{int(x * 1000)}ms": round(1000 * max(rows), 3)
                                    for x, rows in sorted(lateness.items())}
    stale = [r for r in records if r["age"] > MAX_AGE]
    fresh = [r for r in records if r["mode"] == "fresh" and r["age"] <= MAX_AGE]

    def group(rows, key, pred):
        by = defaultdict(lambda: [0, 0])
        for r in rows:
            by[key(r)][1] += 1; by[key(r)][0] += pred(r)
        return {k: frac(*v) for k, v in sorted(by.items())}
    scen = lambda r: ("control" if r["label"] in CONTROLS or r["label"].startswith("queue-") else r["label"])
    control = lambda r: scen(r) == "control"
    small = lambda r: r["exposure"] <= MARGIN
    reasons = defaultdict(int)
    for r in fresh:
        if not r["accept"] and control(r):
            reasons[r["reason"]] += 1
    slack = [r["bound"] - r["age"] for r in records if r["bound"] is not None and control(r) and small(r)]
    counts = {
        "oldAcceptedControlsExposureWithinMargin": frac(sum(r["accept"] for r in stale if control(r) and small(r)),
                                                        sum(1 for r in stale if control(r) and small(r))),
        "oldAcceptedByScenario": group(stale, lambda r: f"{r['label']}|{'after-loop' if r['afterLoop'] else 'first-loop'}", lambda r: r["accept"]),
        "oldAcceptedByExposure": group(stale, lambda r: f"{scen(r)}|{int(r['exposure'] * 1000)}ms", lambda r: r["accept"]),
        "oldAcceptedLongHolds": group([r for r in stale if r["label"] == "long-hold"], lambda r: f"held {round(r['judge'] - r['receipt'])} s", lambda r: r["accept"]),
        "oldAcceptedExamples": [{k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()}
                                for r in stale if r["accept"]][:8],
        "freshRefusedControls": group([r for r in fresh if control(r)], lambda r: "after-loop" if r["afterLoop"] else "first-loop", lambda r: not r["accept"]),
        "freshRefusedControlReasons": dict(reasons),
        "freshRefusedByScenario": group(fresh, scen, lambda r: not r["accept"]),
        "heldWithinLimitAccepted": frac(sum(r["accept"] for r in records if r["mode"] == "held" and r["age"] <= MAX_AGE and control(r)),
                                        sum(1 for r in records if r["mode"] == "held" and r["age"] <= MAX_AGE and control(r))),
        "minBoundMinusTrueAgeControlsExposureWithinMargin": round(min(slack), 4) if slack else None,
        "judgements": len(records)}
    if out["scored"]:
        out["method1"] = counts
    else:
        out["refused"] = f"display log off by up to {max_err * 1000:.1f} ms, more than the {MARGIN * 1000:.0f} ms margin"
        out["method1NotScored"] = counts
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--records", help="also write every judgement (raw times) for independent checks")
    ap.add_argument("--video", default=DEFAULT_VIDEO)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--epochs", type=int, default=24)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--display-log-lag", type=float, default=0.0)
    a = ap.parse_args(argv)
    video = SyntheticVideo() if a.synthetic else DecodedVideo(a.video)
    source = "synthetic codes" if a.synthetic else os.path.basename(a.video)
    records, clock_error, lateness = simulate(video, a.epochs, a.seed, a.display_log_lag)
    out = summarise(records, clock_error, lateness, a.display_log_lag, a.seed, a.epochs, source)
    if not a.synthetic:
        out["decodedCodes"] = frac(sum(c is not None for c in video.codes), len(video.codes))
    out["blendReads"] = {"reads": len(video.cache), "abstained": sum(v is None for v in video.cache.values())}
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    if a.records:
        with open(a.records, "w") as f:
            json.dump(records, f)
    body = out.get("method1") or out["method1NotScored"]
    print(json.dumps(out["harnessTiming"]))
    print(("SCORED" if out["scored"] else "REFUSED: " + out["refused"])
          + f": old accepted (controls, exposure <= margin) {body['oldAcceptedControlsExposureWithinMargin']}")
    return 0 if out["scored"] else 3


if __name__ == "__main__":
    sys.exit(main())
