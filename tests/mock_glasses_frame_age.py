#!/usr/bin/env python3
"""Pure-logic tests for the Phase 5 frame-age rules (docs/MOCK_GLASSES_FRAME_AGE.md). No Simulator needed.

Compiles native/MockGlassesProbe/FrameAgeRules.swift with FrameAgeRulesChecks.swift for macOS into a temporary
folder, runs it, and passes only if every check passes. Also checks statically that the harness never uses the
phone-camera feed, microphone, audio session or speech, and that the live trust gate is not wired to these rules.
Round 2 (2026-11-17): pins the harness timing self-check (frame_age_mac_sim.py, analyze_frame_age.py) so a display
log later than the 0.05 s margin is measured and refuses to score method 1.
Usage: python3 -B tests/mock_glasses_frame_age.py
"""
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(ROOT, "native", "MockGlassesProbe")
EVIDENCE = "/Users/alexmunzon/chess-builds/mock-glasses-phase5-2026-11-16"


def load_analyzer():
    spec = importlib.util.spec_from_file_location("analyze_frame_age", os.path.join(PROBE, "analyze_frame_age.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FrameAgeRules(unittest.TestCase):
    def test_swift_rule_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = os.path.join(tmp, "frame-age-checks")
            build = subprocess.run(
                ["xcrun", "swiftc", "-parse-as-library", "-swift-version", "6", "-module-cache-path", os.path.join(tmp, "mc"),
                 os.path.join(PROBE, "FrameAgeRules.swift"), os.path.join(PROBE, "FrameAgeRulesChecks.swift"), "-o", exe],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr[-3000:])
            run = subprocess.run([exe], capture_output=True, text=True, timeout=120)
            print(run.stdout.strip().splitlines()[-1] if run.stdout.strip() else "(no output)")
            self.assertEqual(run.returncode, 0, run.stdout[-3000:])
            m = re.search(r"^(\d+) of (\d+) passed$", run.stdout, re.M)
            self.assertIsNotNone(m)
            self.assertEqual(m.group(1), m.group(2))
            self.assertGreaterEqual(int(m.group(2)), 30)

    def test_harness_never_uses_camera_microphone_or_speech(self):
        with open(os.path.join(PROBE, "FrameAgeHarness.swift"), encoding="utf-8") as f:
            src = f.read()
        for banned in ("cameraFacing", "AVAudioSession", "AVCaptureDevice", "AVSpeechSynthesizer", "SFSpeech",
                       "requestPermission", "startRegistration", "NSCameraUsageDescription", "NSMicrophoneUsageDescription"):
            self.assertNotIn(banned, src, banned)
        self.assertIn("#if COMPANION_FRAME_AGE_HARNESS && os(iOS) && targetEnvironment(simulator)", src)

    def test_python_rule_copy_matches_swift_rule(self):
        # The Mac harness and the analyzer judge with a Python copy of NonceAgeGate. Compare it with the Swift rule
        # on random and edge cases: bound exactly at the limit, other streams, unread and never-shown codes.
        an = load_analyzer()
        rng = random.Random(7)
        cases = [(3.0, 0.0, 1, 1, 4, 5.0, [(4, 2.0)]), (3.0, 0.25, 1, 1, 4, 3.75, [(4, 1.0)]),
                 (3.0, 0.05, 2, 1, 4, 5.0, [(4, 4.0)]), (3.0, 0.05, 1, 2, 4, 5.0, [(4, 4.0)]),
                 (3.0, 0.05, 0, 0, 4, 5.0, []), (3.0, 0.05, 1, 1, None, 5.0, [(4, 4.0)]),
                 (3.0, 0.05, 1, 1, 6, 5.0, [(6, 5.5)])]
        for _ in range(400):
            ds = [(rng.randrange(5), round(rng.uniform(0, 10), 2)) for _ in range(rng.randrange(6))]
            cases.append((rng.choice([1.0, 3.0]), rng.choice([0.0, 0.05, 0.25]), rng.randrange(3), rng.randrange(3),
                          rng.choice([None, 0, 1, 2, 3, 4]), round(rng.uniform(0, 12), 2), ds))
        driver = """import Foundation
@main struct Diff { static func main() {
  while let line = readLine() {
    let v = line.split(separator: " ").map { Double($0)! }
    var g = NonceAgeGate(maxAge: v[0], displayMargin: v[1])
    if v[2] > 0 { g.startEpoch(UInt64(v[2])) }
    var k = 6
    while k + 1 < v.count { g.recordDisplay(code: Int(v[k]), at: v[k + 1]); k += 2 }
    let r = g.evaluate(code: v[4] < 0 ? nil : Int(v[4]), frameEpoch: UInt64(v[3]), now: v[5])
    print(r.accept, r.reason)
  } } }
"""
        with tempfile.TemporaryDirectory() as tmp:
            src, exe = os.path.join(tmp, "Diff.swift"), os.path.join(tmp, "diff")
            with open(src, "w") as f:
                f.write(driver)
            build = subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-swift-version", "6", "-module-cache-path",
                                    os.path.join(tmp, "mc"), os.path.join(PROBE, "FrameAgeRules.swift"), src, "-o", exe],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr[-3000:])
            lines = [" ".join(str(x) for x in [m, g, ge, fe, -1 if c is None else c, now] + [y for d in ds for y in d])
                     for m, g, ge, fe, c, now, ds in cases]
            out = subprocess.run([exe], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=60).stdout.split("\n")
        agree = 0
        for (m, g, ge, fe, c, now, ds), swift in zip(cases, out):
            def first(code, t, ds=ds):
                times = [x for k, x in ds if k == code]
                return min(times) if times and min(times) <= t else None
            ok, why, _ = an.nonce_evaluate(first, c, fe, ge, now, m, g)
            agree += swift == f"{'true' if ok else 'false'} {why}"
        print(f"python rule copy agrees with Swift: {agree} of {len(cases)}")
        self.assertEqual(agree, len(cases))
        self.assertEqual(out[0], "true ok")      # bound exactly at the limit is accepted (<=)
        self.assertEqual(out[2], "false other-stream")

    def test_mac_harness_scores_against_independent_truth(self):
        # Truth is recomputed here from the raw times of every judgement, with the limit and margin read from the
        # Simulator harness config (FrameAgeHarness.swift), so a constant shared by rule and truth cannot hide an error.
        with open(os.path.join(PROBE, "FrameAgeHarness.swift"), encoding="utf-8") as f:
            swift = f.read()
        limit = float(re.search(r"var nonceMaxAge = ([0-9.]+)", swift).group(1))
        margin = float(re.search(r"var nonceMargin = ([0-9.]+)", swift).group(1))
        sim = os.path.join(PROBE, "frame_age_mac_sim.py")
        with tempfile.TemporaryDirectory() as tmp:
            out, rec = os.path.join(tmp, "out.json"), os.path.join(tmp, "rec.json")
            run = subprocess.run([sys.executable, "-B", sim, "--synthetic", "--epochs", "6", "--out", out, "--records", rec],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            with open(out) as f:
                s = json.load(f)
            with open(rec) as f:
                records = json.load(f)
        self.assertEqual((s["maxAge"], s["margin"]), (limit, margin))
        self.assertTrue(s["scored"])
        self.assertLessEqual(s["harnessTiming"]["displayLogVsTrueDisplayMaxMs"], 1e-6)
        # No picture shows a code more than the margin before the log says it appeared, at any exposure (8-100 ms).
        for exposure, late_ms in s["pictureBeforeLogMaxMs"].items():
            self.assertLessEqual(late_ms, 1000 * margin, exposure)
        controls = ("fresh", "isolated", "burst", "drop", "repeat", "long-hold")
        stale_controls = accepted_controls = 0
        for r in records:
            age = r["judge"] - r["content"]
            self.assertAlmostEqual(r["age"], age, places=9)
            self.assertAlmostEqual(r["exposureEnd"] - r["capture"], r["exposure"], places=9)
            self.assertTrue(0.03 - 1e-9 <= r["receipt"] - r["exposureEnd"] <= 0.12 + 1e-9)
            self.assertGreaterEqual(r["judge"], r["receipt"] - 1e-9)
            if not r["label"].startswith("replay"):
                self.assertEqual(r["content"], r["capture"])
            control = r["label"] in controls or r["label"].startswith("queue-")
            if control and r["exposure"] <= margin:
                if r["bound"] is not None:
                    self.assertGreaterEqual(r["bound"], age - 1e-9, r)      # the rule never under-estimates age
                if age > limit:
                    stale_controls += 1; accepted_controls += r["accept"]
        self.assertEqual(accepted_controls, 0)
        self.assertEqual(s["method1"]["oldAcceptedControlsExposureWithinMargin"], f"0 of {stale_controls}")
        # The probes must be able to fail: holds beyond one 30 s code cycle and pictures after the loop are scored,
        # and a replay of the previous stream or a +1 misread lets old pictures in.
        self.assertTrue(any(r["label"] == "long-hold" and r["judge"] - r["receipt"] >= 30 and r["age"] > limit for r in records))
        self.assertTrue(any(r["afterLoop"] and r["age"] > limit for r in records))
        for probe in ("replay-previous-stream", "misread+1"):
            self.assertTrue(any(r["label"] == probe and r["age"] > limit and r["accept"] for r in records), probe)

    def test_mac_harness_refuses_a_late_display_log(self):
        # A display log 0.23 s late (the old Simulator harness fault) must stop the harness from scoring method 1.
        sim = os.path.join(PROBE, "frame_age_mac_sim.py")
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.json")
            run = subprocess.run([sys.executable, "-B", sim, "--synthetic", "--epochs", "6", "--display-log-lag", "0.23", "--out", bad],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 3, run.stdout + run.stderr)
            self.assertIn("REFUSED", run.stdout)
            with open(bad) as f:
                b = json.load(f)
        self.assertFalse(b["scored"])
        self.assertNotIn("method1", b)
        self.assertGreater(b["harnessTiming"]["displayLogVsTrueDisplayMaxMs"], 50.0)
        # Unscored diagnosis: the late log makes the rule's bound smaller than the true age (it would under-estimate).
        self.assertLess(b["method1NotScored"]["minBoundMinusTrueAgeControlsExposureWithinMargin"], -0.1)

    def test_analyzer_measures_display_log_error(self):
        # Code 1 is first seen in a picture 0.2 s before the modelled log (anchor + 2 s) says it was shown.
        an = load_analyzer()
        cfg = {"slotSeconds": 2.0, "codes": 15, "nonceMargin": 0.05, "nonceMaxAge": 3.0}
        frames = [{"id": 0, "epoch": 1, "pts": 0.0, "sdkTime": 100.0, "code": 0},
                  {"id": 1, "epoch": 1, "pts": 1.8, "sdkTime": 101.8, "code": 1}]
        t = an.display_log_lateness(frames, cfg)
        self.assertAlmostEqual(t["maxLateMs"], 200.0, places=3)
        self.assertEqual(t["codesLaterThanMargin"], "1 of 2")
        _, _, modelled, readback = an.display_logs(frames, cfg)
        # Held 3.1 s after its callback: the modelled log accepts it, the readback log rejects it.
        self.assertTrue(an.nonce_evaluate(modelled(1), 1, 1, 1, 104.9, 3.0, 0.05)[0])
        self.assertEqual(an.nonce_evaluate(readback(1), 1, 1, 1, 104.9, 3.0, 0.05)[1], "too-old")

    def test_recorded_runs_refused_and_rejudged(self):
        # Pins the round-2 finding on the Phase 5 Simulator evidence (skipped where that folder is absent).
        report = os.path.join(EVIDENCE, "run2", "container", "Documents", "frame-age-report.json")
        if not os.path.exists(report):
            self.skipTest(f"no evidence at {report}")
        out = subprocess.run([sys.executable, "-B", os.path.join(PROBE, "analyze_frame_age.py"), report],
                             capture_output=True, text=True, check=True).stdout
        s = json.loads(out)
        t = s["harnessTiming"]
        self.assertTrue(t["refuseMethod1"])
        self.assertGreater(t["maxLateMs"], 50.0)
        n, m = t["pythonPortAgreesWithRecordedSwiftVerdicts"].split(" of ")
        self.assertEqual(n, m)
        self.assertFalse(s["methods"]["m1"]["scored"])
        self.assertEqual(s["methods"]["m1"]["recordedNotScored"]["staleRejected"], "51 of 54")
        self.assertEqual(s["methods"]["m1readback"]["staleRejected"], "54 of 54")

    def test_live_gate_untouched(self):
        # The rules are harness-only: no app or capture source refers to them.
        for rel in ("native/ChessCompanionCapture/Sources/ChessCompanionCapture", "native/ChessCompanionApp"):
            folder = os.path.join(ROOT, rel)
            for name in os.listdir(folder):
                if name.endswith(".swift"):
                    with open(os.path.join(folder, name), encoding="utf-8") as f:
                        text = f.read()
                    for symbol in ("NonceAgeGate", "OffsetMonitorGate", "LivenessBudgetGate"):
                        self.assertNotIn(symbol, text, f"{rel}/{name} uses {symbol}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
