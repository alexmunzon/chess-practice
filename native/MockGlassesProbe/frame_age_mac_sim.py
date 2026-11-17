#!/usr/bin/env python3
"""Method 1 (on-screen code) frame-age study on the Mac: simulated video only, no Simulator, no Meta code.

usage: frame_age_mac_sim.py --out OUT.json [--video replay-14.mp4 | --synthetic] [--epochs 24] [--seed 1]
                            [--display-log-lag SECONDS] [--records RECORDS.json]
                            [--drop-session-value] [--drop-check-digits]
                            [--restart-at SECONDS [--reuse-session-on-restart]]

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
- code (2026-11-17): the display shows the full code of analyze_frame_age.encode_code: a session value drawn per
  stream (own seeded generator), the counter (the video's code index) and 2 check digits. A picture reads the full
  code of the display frame the project's reader decoded (the reader decodes the code band as one unit).
  The gate decodes it with the app's own current session value (read_code), then applies the unchanged rule.
  --drop-session-value gives every stream the same session value and --drop-check-digits skips the check; both
  exist only to show that the harness can still report accepted old pictures.
- restart (round 2, off by default): --restart-at S restarts the display session S seconds into every stream, as the
  display must when its 2-symbol counter runs out (961 values): the video starts again at frame 0, the display log is
  emptied and a new session value is drawn; the stream itself goes on. --reuse-session-on-restart keeps the old value
  (fault probe). A picture whose exposure spans the restart is counted as unreadable.
- reader fallback (round 2, every run): each picture is also judged as if the reader returned the last code that read
  valid in this stream whenever it cannot read a valid code (record field acceptFallbackReader). This is a forbidden
  reader design; scoring it on the same pictures leaves every other count unchanged.
Truth: age = judge time - the moment the shown content was on screen (exposure start; for a replayed screen, the
moment the replayed content was on the real display). Stale = age > nonceMaxAge. Every picture is scored, including
those after the video loops (codes repeat) and holds longer than the 30 s code cycle.

Scenarios. Controls the rule is built to handle (old accepted should be 0 when exposure <= margin): fresh, isolated
holds 0.1-10 s, queues, bursts, drops, repeated copies, long holds 30-60 s. Weakness probes, which break an
assumption of the rule on purpose (a non-zero count is a finding about the method, not a harness bug): a second
screen replaying the display 2, 5 or 20 s late or from the previous stream; misreads of the code: the counter
symbols read as the neighbouring counter (+1 newer, -1 older) with the other symbols as shown, one random symbol
wrong, and (residual, no check can catch it) the complete valid code of the next counter; exposure of 100 ms
(longer than the 50 ms margin).

Self-check before scoring: the display log is compared with the true first display time of each code, computed
separately from the video's code track. If they differ by more than the margin, nothing is scored (exit 3).
The rule is judged with analyze_frame_age.coded_evaluate: read_code, then nonce_evaluate, a port of NonceAgeGate
checked against the Swift rule.
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


an = load("analyze_frame_age", os.path.join(HERE, "analyze_frame_age.py"))
MISREADS = ["counter+1", "counter-1", "symbol", "codeword+1"]


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


def misread(model, symbols, session, counter, rng):
    """Reader errors on the full code. Not shaped to the check: a random symbol, or the counter field misread."""
    if model in ("counter+1", "counter-1"):
        wrong = an.encode_code(session, (counter + (1 if model == "counter+1" else -1)) % CODES)
        cut = (an.SESSION_SYMBOLS, an.SESSION_SYMBOLS + an.COUNTER_SYMBOLS)
        return symbols[:cut[0]] + wrong[cut[0]:cut[1]] + symbols[cut[1]:]
    if model == "symbol":
        pos = rng.randrange(len(symbols))
        value = rng.choice([x for x in range(an.CODE_BASE) if x != symbols[pos]])
        return symbols[:pos] + (value,) + symbols[pos + 1:]
    return an.encode_code(session, (counter + 1) % CODES)          # codeword+1: a complete valid code


def simulate(video, epochs, seed, lag, drop_session=False, drop_check=False, restart_at=None, reuse_on_restart=False):
    """restart_at (seconds into each stream, default off): the display session restarts inside the stream, as it must
    when the counter runs out: the video (counter) starts again at frame 0, the display log is emptied and a new
    session value is drawn. The stream (epoch) does not change. reuse_on_restart keeps the old session value (fault)."""
    rng = random.Random(seed)
    # Own generators, so the scenario draws are the same as before the code change (paired before/after runs).
    session_rng, misread_rng = random.Random(f"session-{seed}"), random.Random(f"misread-{seed}")
    sessions = [(0,) * an.SESSION_SYMBOLS if drop_session else
                tuple(session_rng.randrange(an.CODE_BASE) for _ in range(an.SESSION_SYMBOLS)) for _ in range(epochs + 3)]
    # Values for the restarted display sessions, drawn after the first ones so a run without restarts is unchanged.
    restart_sessions = [sessions[k] if reuse_on_restart or drop_session else
                        tuple(session_rng.randrange(an.CODE_BASE) for _ in range(an.SESSION_SYMBOLS)) for k in range(epochs + 3)]
    records, clock_error, lateness = [], [], defaultdict(list)
    delay_i = long_i = replay_i = misread_i = 0
    period = EPOCH_SECONDS + 1.0
    truth_first = true_first_display(video)

    def stream_start(k):
        return 1000.0 + (k - 1) * period

    def display_session(k, t):
        """Display session of stream k at time t: (index 0 or 1, its start time, its session value)."""
        r = None if restart_at is None else stream_start(k) + restart_at
        if r is not None and t >= r:
            return 1, r, restart_sessions[k]
        return 0, stream_start(k), sessions[k]

    def display_log(t0, length):
        # Display log from the frame counter (first display frame that shows each code), plus the injected lag.
        log = {}
        for d in range(int(length * FPS)):
            c = video.codes[d % FILE_FRAMES]
            if c is not None and c not in log:
                log[c] = t0 + d / FPS + lag
        return log

    start = stream_start(1)
    for e in range(1, epochs + 1):
        next_start = start + period
        exposure = EXPOSURES[(e - 1) % len(EXPOSURES)]
        logs = [display_log(start, EPOCH_SECONDS if restart_at is None else restart_at)]
        if restart_at is not None:
            logs.append(display_log(start + restart_at, EPOCH_SECONDS - restart_at))
        for k, lg in enumerate(logs):
            t0 = start if k == 0 else start + restart_at
            clock_error += [lg[c] - (t0 + truth_first[c]) for c in lg]
        last_valid = {}                      # fallback reader: last code that read valid in this stream
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
            src_epoch = e if content >= start else e - 1                  # the previous stream ran the same video
            src_k, src_start, src_session = display_session(src_epoch, content)
            true_code, d0 = read_picture(video, src_start, content, exposure)
            if display_session(src_epoch, content + exposure)[0] != src_k:
                true_code = None             # exposure spans the restart: two different codes blended, not modelled
            symbols = None if true_code is None else an.encode_code(src_session, true_code)
            if kind == "misread" and symbols is not None:
                model = MISREADS[misread_i % len(MISREADS)]; misread_i += 1
                symbols = misread(model, symbols, src_session, true_code, misread_rng)
                label = f"misread-{model}"
            code, _ = an.read_code(symbols, display_session(e, s)[2], not drop_check)   # decoded counter (None if refused)
            if kind in CONTROLS and code is not None and src_epoch == e and code in logs[src_k]:
                lateness[exposure].append(logs[src_k][code] - s)
            receipt = s + exposure + rng.uniform(*LATENCY)
            # Forbidden reader design, scored on the same pictures: when the code cannot be read as valid with the
            # app's current session value, the reader returns the last code that did read valid in this stream.
            app_session = display_session(e, receipt)[2]
            if an.read_code(symbols, app_session)[0] is not None:
                last_valid[e] = symbols
                fallback_symbols = symbols
            else:
                fallback_symbols = last_valid.get(e)
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
                # The gate knows only its own current session value and its own display log (emptied at a restart;
                # another stream's log is never consulted, the rule refuses other streams first).
                gate_k, _, gate_session = display_session(gate_epoch, now)
                log = logs[gate_k] if gate_epoch == e else logs[0]
                first = lambda c, t, lg=log: lg[c] if c in lg and lg[c] <= t else None
                ok, why, bound = an.coded_evaluate(first, symbols, gate_session, e, gate_epoch, now, MAX_AGE, MARGIN,
                                                   verify_check=not drop_check)
                fb_ok = an.coded_evaluate(first, fallback_symbols, gate_session, e, gate_epoch, now, MAX_AGE, MARGIN,
                                          verify_check=not drop_check)[0]
                records.append({"epoch": e, "label": label, "mode": mode, "exposure": exposure, "capture": s,
                                "exposureEnd": s + exposure, "receipt": receipt, "judge": now, "content": content,
                                "afterLoop": d0 >= FILE_FRAMES, "code": code, "trueCode": true_code,
                                "symbols": symbols, "gateEpoch": gate_epoch, "gateSession": gate_session,
                                "age": now - content, "accept": ok, "reason": why, "bound": bound,
                                "acceptFallbackReader": fb_ok})
        start = next_start
    return records, clock_error, lateness, sessions + (restart_sessions if restart_at is not None else [])


def frac(n, m):
    return f"{n} of {m}"


def summarise(records, clock_error, lateness, lag, seed, epochs, source, restart_at=None):
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
    # Forbidden reader design scored on the same pictures (other rows unchanged): the reader returns the last code
    # that read valid in this stream whenever it cannot read a valid code.
    counts["readerFallbackOldAccepted"] = frac(sum(r["acceptFallbackReader"] for r in stale), len(stale))
    counts["readerFallbackOldAcceptedByScenario"] = group(stale, scen, lambda r: r["acceptFallbackReader"])
    counts["readerFallbackFreshRefused"] = frac(sum(not r["acceptFallbackReader"] for r in fresh), len(fresh))
    if restart_at is not None:
        # Pictures whose content was shown before the restart of their own stream and judged after it.
        t_r = lambda r: 1000.0 + (r["epoch"] - 1) * (EPOCH_SECONDS + 1.0) + restart_at
        across = [r for r in records if r["epoch"] == r["gateEpoch"]
                  and t_r(r) - restart_at <= r["content"] < t_r(r) <= r["judge"]]
        counts["acrossRestartOldAccepted"] = frac(sum(r["accept"] for r in across if r["age"] > MAX_AGE),
                                                  sum(1 for r in across if r["age"] > MAX_AGE))
        counts["acrossRestartFreshRefused"] = frac(sum(not r["accept"] for r in across if r["age"] <= MAX_AGE and r["mode"] == "fresh"),
                                                   sum(1 for r in across if r["age"] <= MAX_AGE and r["mode"] == "fresh"))
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
    ap.add_argument("--drop-session-value", action="store_true", help="fault probe: one session value for all streams")
    ap.add_argument("--drop-check-digits", action="store_true", help="fault probe: the gate skips the check digits")
    ap.add_argument("--restart-at", type=float, help="restart the display session this many seconds into each stream "
                    "(counter and log reset, new session value), as when the counter runs out")
    ap.add_argument("--reuse-session-on-restart", action="store_true",
                    help="fault probe: keep the old session value at the restart")
    a = ap.parse_args(argv)
    video = SyntheticVideo() if a.synthetic else DecodedVideo(a.video)
    source = "synthetic codes" if a.synthetic else os.path.basename(a.video)
    records, clock_error, lateness, sessions = simulate(video, a.epochs, a.seed, a.display_log_lag,
                                                        a.drop_session_value, a.drop_check_digits,
                                                        a.restart_at, a.reuse_session_on_restart)
    out = summarise(records, clock_error, lateness, a.display_log_lag, a.seed, a.epochs, source, a.restart_at)
    out["code"] = {"base": an.CODE_BASE, "sessionSymbols": an.SESSION_SYMBOLS, "counterSymbols": an.COUNTER_SYMBOLS,
                   "checkSymbols": an.CHECK_SYMBOLS, "dropSessionValue": a.drop_session_value,
                   "dropCheckDigits": a.drop_check_digits, "restartAt": a.restart_at,
                   "reuseSessionOnRestart": a.reuse_session_on_restart,
                   "distinctSessionValues": frac(len(set(sessions)), len(sessions))}
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
    print(f"reader returning the last valid code, old accepted {body['readerFallbackOldAccepted']}"
          + (f"; across the restart, old accepted {body['acrossRestartOldAccepted']}" if a.restart_at is not None else ""))
    return 0 if out["scored"] else 3


if __name__ == "__main__":
    sys.exit(main())
