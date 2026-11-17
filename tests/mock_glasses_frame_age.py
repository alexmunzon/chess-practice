#!/usr/bin/env python3
"""Pure-logic tests for the Phase 5 frame-age rules (docs/MOCK_GLASSES_FRAME_AGE.md). No Simulator needed.

Compiles native/MockGlassesProbe/FrameAgeRules.swift with FrameAgeRulesChecks.swift for macOS into a temporary
folder, runs it, and passes only if every check passes. Also checks statically that the harness never uses the
phone-camera feed, microphone, audio session or speech, and that the live trust gate is not wired to these rules.
Round 2 (2026-11-17): pins the harness timing self-check (frame_age_mac_sim.py, analyze_frame_age.py) so a display
log later than the 0.05 s margin is measured and refuses to score method 1.
Code round (2026-11-17): the on-screen code carries a per-session value and check digits; tests pin that a replayed
earlier session and single-symbol / neighbouring-counter misreads are refused, and that the harness reports accepted
old pictures again when either part is removed.
Code round 2 (2026-11-17, review fixes): encode_code refuses a bad session value and counter 961; session values use
all 4 symbols and differ across seeds; one-symbol misreads reach every position; a restart inside a stream needs a new
session value; the forbidden "last valid code" reader fallback is measured; the check-digit probe has a 10% floor.
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


_SIM_RUNS = {}


def run_mac_sim(*flags):
    """Synthetic 6-stream run of the Mac harness, cached per flag set. Returns (summary, records)."""
    if flags not in _SIM_RUNS:
        sim = os.path.join(PROBE, "frame_age_mac_sim.py")
        with tempfile.TemporaryDirectory() as tmp:
            out, rec = os.path.join(tmp, "out.json"), os.path.join(tmp, "rec.json")
            run = subprocess.run([sys.executable, "-B", sim, "--synthetic", "--epochs", "6", *flags, "--out", out,
                                  "--records", rec], capture_output=True, text=True)
            if run.returncode != 0:
                raise AssertionError(run.stdout + run.stderr)
            with open(out) as f:
                summary = json.load(f)
            with open(rec) as f:
                records = json.load(f)
        _SIM_RUNS[flags] = (summary, records)
    return _SIM_RUNS[flags]


def old_accepted(records, label, limit=3.0):
    rows = [r for r in records if r["label"] == label and r["judge"] - r["content"] > limit]
    return sum(r["accept"] for r in rows), len(rows)


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
        # and a reader returning the complete valid code of the next counter (no check can see it) lets old pictures
        # in. Replays of the previous stream and +1 counter misreads are pinned in the code tests below.
        self.assertTrue(any(r["label"] == "long-hold" and r["judge"] - r["receipt"] >= 30 and r["age"] > limit for r in records))
        self.assertTrue(any(r["afterLoop"] and r["age"] > limit for r in records))
        self.assertTrue(any(r["label"] == "misread-codeword+1" and r["age"] > limit and r["accept"] for r in records))

    def test_code_check_digits_detect_symbol_and_counter_errors(self):
        # Every single-symbol change, every 2-symbol change and every neighbouring-counter misread is refused;
        # a valid code of another session is refused; random strings pass the check about 1 in 31^2.
        an = load_analyzer()
        rng = random.Random(11)
        n_sym = an.CODE_LENGTH
        self.assertEqual((an.CODE_BASE, an.SESSION_SYMBOLS, an.COUNTER_SYMBOLS, an.CHECK_SYMBOLS), (31, 4, 2, 2))
        cut = (an.SESSION_SYMBOLS, an.SESSION_SYMBOLS + an.COUNTER_SYMBOLS)
        single = double = neighbour = 0
        for _ in range(40):
            session = tuple(rng.randrange(31) for _ in range(an.SESSION_SYMBOLS))
            counter = rng.choice([0, 1, 14, 30, 31, 32, 500, 959, 960, rng.randrange(961)])
            code = an.encode_code(session, counter)
            self.assertEqual(len(code), n_sym)
            self.assertEqual(an.read_code(code, session), (counter, "ok"))
            for pos in range(n_sym):
                for v in range(31):
                    if v != code[pos]:
                        bad = code[:pos] + (v,) + code[pos + 1:]
                        self.assertEqual(an.read_code(bad, session), (None, "check-digits-failed"), (code, pos, v))
                        single += 1
            for _ in range(200):
                p1, p2 = rng.sample(range(n_sym), 2)
                bad = list(code)
                bad[p1] = (bad[p1] + rng.randrange(1, 31)) % 31
                bad[p2] = (bad[p2] + rng.randrange(1, 31)) % 31
                # The check digits alone (session not compared) must refuse every 2-symbol change.
                self.assertEqual(an.read_code(bad, session, verify_session=False), (None, "check-digits-failed"), (code, bad))
                double += 1
            for step in (1, -1):
                if 0 <= counter + step < 961:
                    wrong = an.encode_code(session, counter + step)
                    bad = code[:cut[0]] + wrong[cut[0]:cut[1]] + code[cut[1]:]
                    self.assertEqual(an.read_code(bad, session), (None, "check-digits-failed"))
                    neighbour += 1
            for pos in range(an.SESSION_SYMBOLS):           # a session differing in any one symbol is another session
                other = session[:pos] + ((session[pos] + 1) % 31,) + session[pos + 1:]
                self.assertEqual(an.read_code(an.encode_code(other, counter), session), (None, "other-session"))
        self.assertEqual(an.read_code(None, (0, 0, 0, 0)), (None, "unreadable-code"))
        valid = an.encode_code((0, 0, 0, 0), 0)                                  # all symbols 0
        for bad in (valid + (0,), valid[:-1], (31,) + valid[1:]):
            self.assertEqual(an.read_code(bad, (0, 0, 0, 0)), (None, "malformed-code"), bad)
        passes = sum(an.read_code([rng.randrange(31) for _ in range(n_sym)], (0, 0, 0, 0), verify_session=False)[0] is not None
                     for _ in range(96100))
        print(f"code: single-symbol changes refused {single} of {single}, 2-symbol {double} of {double}, "
              f"neighbouring counter {neighbour} of {neighbour}; random strings passing the check {passes} of 96100")
        self.assertTrue(40 <= passes <= 170, passes)       # expected 100 (1 in 961)

    def test_previous_session_replay_refused_and_harness_can_fail(self):
        # A second screen replaying the previous stream showed codes the current display also showed (2033 of 8712
        # old pictures accepted before). With a session value they are refused; without it the count comes back.
        s, records = run_mac_sim()
        n, m = old_accepted(records, "replay-previous-stream")
        self.assertGreater(m, 100)
        self.assertEqual(n, 0)
        self.assertTrue(any(r["label"] == "replay-previous-stream" and r["reason"] == "other-session" for r in records))
        by_stream = {r["gateEpoch"]: tuple(r["gateSession"]) for r in records}
        self.assertEqual(len(set(by_stream.values())), len(by_stream))       # one session value per stream
        self.assertEqual(s["code"]["distinctSessionValues"], "9 of 9")
        _, dropped = run_mac_sim("--drop-session-value")
        n_drop, m_drop = old_accepted(dropped, "replay-previous-stream")
        print(f"previous-stream replay, old accepted: {n} of {m}; without session value {n_drop} of {m_drop}")
        self.assertEqual(m_drop, m)
        self.assertGreater(n_drop, m_drop // 10)

    def test_misreads_refused_and_harness_can_fail(self):
        # Reader errors not shaped to the code: one random symbol wrong, or the counter symbols read as the
        # neighbouring counter. All are refused by the check digits; without the check, +1 misreads get through.
        an = load_analyzer()
        _, records = run_mac_sim()
        for label in ("misread-counter+1", "misread-counter-1", "misread-symbol"):
            rows = [r for r in records if r["label"] == label]
            self.assertGreater(len(rows), 30, label)
            self.assertEqual(sum(r["accept"] for r in rows), 0, label)      # fresh or old: a misread is never accepted
            self.assertTrue(all(r["reason"] in ("check-digits-failed", "other-stream") for r in rows), label)
        # The gate decides from what the app has at runtime: the read symbols and its own current session value.
        for r in records:
            counter, _ = an.read_code(r["symbols"], r["gateSession"])
            if r["accept"]:
                self.assertIsNotNone(counter, r)
                self.assertEqual(r["epoch"], r["gateEpoch"])
        _, dropped = run_mac_sim("--drop-check-digits")
        n, m = old_accepted(records, "misread-counter+1")
        n_drop, m_drop = old_accepted(dropped, "misread-counter+1")
        print(f"counter +1 misread, old accepted: {n} of {m}; without check digits {n_drop} of {m_drop}")
        # A +1 misread of an old picture is accepted whenever the next code has been on screen for under 3 s: 21% on
        # this run, 17% (157 of 916) on the 33-stream video runs. A floor of 10% shows the probe still has its power.
        self.assertGreaterEqual(m_drop, 40)
        self.assertGreaterEqual(n_drop, m_drop // 10)
        self.assertEqual(m_drop, m)

    def test_encode_refuses_bad_session_value_and_counter_overflow(self):
        # The counter has 961 values and never wraps: at 961 the display must end the session (new session value).
        an = load_analyzer()
        self.assertEqual(an.COUNTER_VALUES, 961)
        self.assertEqual(an.COUNTER_VALUES * 2.0 / 60, 32.03333333333333)     # minutes at one code every 2 s
        session = (3, 1, 4, 1)
        self.assertEqual(an.read_code(an.encode_code(session, 960), session), (960, "ok"))
        for counter in (961, 962, 1922, -1, 1.0):
            with self.assertRaises(ValueError, msg=counter):
                an.encode_code(session, counter)
        for bad in ((3, 1, 4), (3, 1, 4, 1, 5), (3, 1, 4, 31), (3, 1, -1, 1), (3, 1, 4, 1.0), ()):
            with self.assertRaises(ValueError, msg=bad):
                an.encode_code(bad, 0)

    def test_session_values_use_the_full_space_and_differ_across_seeds(self):
        # 4 random symbols per value (31^4 = 923,521), drawn anew for every stream and every seed.
        _, r1 = run_mac_sim()
        _, r2 = run_mac_sim("--seed", "2")
        v1 = {tuple(r["gateSession"]) for r in r1}
        v2 = {tuple(r["gateSession"]) for r in r2}
        self.assertEqual(len(v1), len({r["gateEpoch"] for r in r1}))       # one value per stream the gate saw (7)
        self.assertEqual(len(v2), len({r["gateEpoch"] for r in r2}))
        self.assertGreaterEqual(len(v1), 6)
        self.assertEqual(v1 & v2, set())                                      # not the same values for every seed
        pooled = v1 | v2
        for pos in range(4):                                                  # 14 draws of 31: about 11 distinct
            self.assertGreaterEqual(len({v[pos] for v in pooled}), 6, pos)

    def test_one_symbol_misread_hits_every_position_and_is_refused(self):
        # The "one random symbol wrong" probe must reach the session, counter and check-digit symbols alike.
        an = load_analyzer()
        _, records = run_mac_sim()
        positions = {}
        for r in records:
            if r["label"] != "misread-symbol" or r["symbols"] is None or r["epoch"] != r["gateEpoch"]:
                continue
            shown = an.encode_code(r["gateSession"], r["trueCode"])          # the stream's own value, no restart here
            diff = [i for i, (a, b) in enumerate(zip(shown, r["symbols"])) if a != b]
            self.assertEqual(len(diff), 1, r)
            positions[diff[0]] = positions.get(diff[0], 0) + 1
            self.assertFalse(r["accept"])
            self.assertEqual(r["reason"], "check-digits-failed")
        print(f"one-symbol misreads by position: {dict(sorted(positions.items()))}")
        self.assertEqual(set(positions), set(range(an.CODE_LENGTH)))
        self.assertGreaterEqual(min(positions.values()), 10)

    def test_restart_inside_a_stream_needs_a_new_session_value(self):
        # The display restarts 50 s into each stream (counter and log back to the start), as it must when the counter
        # runs out. Pictures shown before the restart and judged after it: refused with a new session value; with the
        # old value kept, the emptied log no longer knows their codes were shown earlier and old pictures get in.
        def across(records):
            stale = fresh_after = fresh_after_ok = 0
            acc = 0
            for r in records:
                s0 = 1000.0 + (r["epoch"] - 1) * 101.0
                t_r = s0 + 50.0
                if r["epoch"] == r["gateEpoch"] and s0 <= r["content"] < t_r <= r["judge"] and r["judge"] - r["content"] > 3.0:
                    stale += 1; acc += r["accept"]
                if (r["label"] == "fresh" and r["epoch"] == r["gateEpoch"] and t_r + 2.0 <= r["content"] < t_r + 28.0
                        and r["judge"] - r["content"] <= 3.0):
                    fresh_after += 1; fresh_after_ok += r["accept"]
            return acc, stale, fresh_after_ok, fresh_after
        s, redrawn = run_mac_sim("--restart-at", "50")
        _, reused = run_mac_sim("--restart-at", "50", "--reuse-session-on-restart")
        n, m, ok, f = across(redrawn)
        n_re, m_re, _, _ = across(reused)
        print(f"restart inside a stream, old accepted: new session value {n} of {m}; old value kept {n_re} of {m_re}; "
              f"fresh after the restart accepted {ok} of {f}")
        self.assertGreaterEqual(m, 100)
        self.assertEqual(n, 0)
        self.assertEqual(m_re, m)
        self.assertGreaterEqual(n_re, m_re // 10)
        self.assertEqual(s["method1"]["acrossRestartOldAccepted"], f"0 of {m}")
        self.assertTrue(s["method1"]["oldAcceptedControlsExposureWithinMargin"].startswith("0 of "))
        self.assertEqual(s["code"]["distinctSessionValues"], "18 of 18")
        self.assertGreater(ok, f * 0.9)                    # the new session works: fresh pictures accepted again

    def test_reader_fallback_to_last_valid_code_lets_old_pictures_in(self):
        # Forbidden reader design, scored on the same pictures: when the code is unreadable or invalid, the reader
        # returns the last code that read valid. The real reader refuses those pictures.
        an = load_analyzer()
        s, records = run_mac_sim()
        stale = [r for r in records if r["judge"] - r["content"] > 3.0]
        fb = [r for r in stale if r["acceptFallbackReader"]]
        print(f"reader fallback, old accepted {len(fb)} of {len(stale)}; real reader {sum(r['accept'] for r in stale)}")
        self.assertEqual(s["method1"]["readerFallbackOldAccepted"], f"{len(fb)} of {len(stale)}")
        # 1.0% here, 1.2% (277 of 23518) on the reviewer's 33-stream synthetic run; a floor of 0.5% keeps the probe honest.
        self.assertGreaterEqual(len(fb), len(stale) // 200)
        # Every extra accept is a picture whose own code did not read valid for the gate.
        for r in fb:
            if not r["accept"]:
                self.assertIsNone(an.read_code(r["symbols"], r["gateSession"])[0], r)
        labels = {r["label"] for r in fb if not r["accept"]}
        self.assertTrue({"replay-previous-stream", "misread-symbol"} <= labels, labels)

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
