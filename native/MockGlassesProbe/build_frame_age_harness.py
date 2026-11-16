#!/usr/bin/env python3
"""Build the Phase 5 frame-age harness: a separate Simulator-only app containing Meta's mock-glasses SDK.

usage: build_frame_age_harness.py --frameworks DIR --video replay-14.mp4 --out DIR

Reuses, read-only, the pins and Info.plist keys of native/ChessCompanionApp/prepare_app.py (imported, never run),
so the harness declares exactly what the Phase 3 mock copy declares and nothing more. The app's own builds are
not touched. Output: DIR/FrameAgeHarness.app (bundle local.chesscompanion.mockglasses.frameage), ad hoc signed for
the Simulator only, plus DIR/build-report.json. Compiled sources: the capture contracts, coordinator and DAT
adapter, MockGlassesSource.swift (for its code reader; its runner never starts here), FrameAgeRules.swift and
FrameAgeHarness.swift, with -D COMPANION_MOCK_GLASSES -D COMPANION_FRAME_AGE_HARNESS.
"""
import argparse
import hashlib
import importlib.util
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ID = "local.chesscompanion.mockglasses.frameage"
EXECUTABLE = "FrameAgeHarness"
SOURCES = [
    "native/ChessCompanionCapture/Sources/ChessCompanionCapture/CaptureContracts.swift",
    "native/ChessCompanionCapture/Sources/ChessCompanionCapture/CaptureCoordinator.swift",
    "native/ChessCompanionCapture/Sources/ChessCompanionCapture/IOSAdapters.swift",
    "native/ChessCompanionApp/MockGlassesSource.swift",
    "native/MockGlassesProbe/FrameAgeRules.swift",
    "native/MockGlassesProbe/FrameAgeHarness.swift",
]


def load_prepare_app():
    spec = importlib.util.spec_from_file_location("prepare_app_pins", ROOT / "native/ChessCompanionApp/prepare_app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # defines constants and functions only; main() runs only as a script
    return module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frameworks", type=Path, required=True)
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    pa = load_prepare_app()
    out = a.out.resolve()
    if out.exists():
        sys.exit(f"output exists: {out}")
    for name, pin in pa.MOCK_GLASSES_FRAMEWORKS.items():
        folder = a.frameworks / f"{name}.framework"
        if folder.is_symlink() or not folder.is_dir() or sha(folder / name) != pin:
            sys.exit(f"framework missing or not matching its pin: {folder}")
    if sha(a.video) != pa.MOCK_GLASSES_VIDEO_SHA256:
        sys.exit("video does not match its pinned SHA-256")
    app = out / f"{EXECUTABLE}.app"
    (app / "Frameworks").mkdir(parents=True)
    (app / "FrameAge").mkdir()
    shutil.copyfile(a.video, app / "FrameAge" / "replay-14.mp4")
    for name in pa.MOCK_GLASSES_FRAMEWORKS:
        shutil.copytree(a.frameworks / f"{name}.framework", app / "Frameworks" / f"{name}.framework", symlinks=True)
        if sha(app / "Frameworks" / f"{name}.framework" / name) != pa.MOCK_GLASSES_FRAMEWORKS[name]:
            sys.exit(f"embedded copy of {name} does not match its pin")
    info = {"CFBundleIdentifier": BUNDLE_ID, "CFBundleExecutable": EXECUTABLE, "CFBundleName": "FrameAgeHarness",
            "CFBundleDisplayName": "Frame Age Harness", "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "1", "MinimumOSVersion": "17.2", "UIDeviceFamily": [1], "CFBundleSupportedPlatforms": ["iPhoneSimulator"],
            "UIApplicationSceneManifest": {"UIApplicationSupportsMultipleScenes": False}, "UILaunchScreen": {},
            "UISupportedInterfaceOrientations": ["UIInterfaceOrientationPortrait"]}
    info.update(json.loads(json.dumps(pa.MOCK_GLASSES_INFO)))
    if {"NSCameraUsageDescription", "NSMicrophoneUsageDescription"} & set(info):
        sys.exit("harness must not declare camera or microphone usage")
    (app / "Info.plist").write_bytes(plistlib.dumps(info))
    entitlements = out / "frame-age.entitlements"
    entitlements.write_bytes(plistlib.dumps({"application-identifier": BUNDLE_ID, "keychain-access-groups": [BUNDLE_ID]}))
    sdk = subprocess.check_output(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"], text=True).strip()
    swiftc = subprocess.check_output(["xcrun", "--find", "swiftc"], text=True).strip()
    command = [swiftc, "-parse-as-library", "-swift-version", "6", "-O", "-target", "arm64-apple-ios17.2-simulator", "-sdk", sdk,
               "-D", "COMPANION_MOCK_GLASSES", "-D", "COMPANION_FRAME_AGE_HARNESS",
               "-module-cache-path", str(out / "module-cache"), "-emit-executable", "-Xlinker", "-no_adhoc_codesign",
               "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT", "-Xlinker", "__entitlements", "-Xlinker", str(entitlements),
               "-F", str(app / "Frameworks"), *[f for n in pa.MOCK_GLASSES_FRAMEWORKS for f in ("-framework", n)],
               "-Xlinker", "-rpath", "-Xlinker", "@executable_path/Frameworks",
               "-o", str(app / EXECUTABLE), *[str(ROOT / s) for s in SOURCES]]
    done = subprocess.run(command, capture_output=True, text=True)
    (out / "compile.stderr.txt").write_text(done.stderr)
    if done.returncode != 0:
        print(done.stderr[-4000:], file=sys.stderr)
        sys.exit(f"swiftc failed with exit {done.returncode}")
    for name in pa.MOCK_GLASSES_FRAMEWORKS:
        subprocess.run(["codesign", "--force", "--sign", "-", str(app / "Frameworks" / f"{name}.framework")], check=True, capture_output=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True, capture_output=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True, capture_output=True)
    report = {"app": str(app), "bundleIdentifier": BUNDLE_ID, "command": command, "exitCode": done.returncode,
              "sourceSha256": {s: sha(ROOT / s) for s in SOURCES}, "frameworkPins": pa.MOCK_GLASSES_FRAMEWORKS,
              "videoSha256": pa.MOCK_GLASSES_VIDEO_SHA256, "signed": "ad-hoc (Simulator only)", "executed": False}
    (out / "build-report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(f"BUILD OK {app}")


if __name__ == "__main__":
    main()
