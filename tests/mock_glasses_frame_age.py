#!/usr/bin/env python3
"""Pure-logic tests for the Phase 5 frame-age rules (docs/MOCK_GLASSES_FRAME_AGE.md). No Simulator needed.

Compiles native/MockGlassesProbe/FrameAgeRules.swift with FrameAgeRulesChecks.swift for macOS into a temporary
folder, runs it, and passes only if every check passes. Also checks statically that the harness never uses the
phone-camera feed, microphone, audio session or speech, and that the live trust gate is not wired to these rules.
Usage: python3 -B tests/mock_glasses_frame_age.py
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(ROOT, "native", "MockGlassesProbe")


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
