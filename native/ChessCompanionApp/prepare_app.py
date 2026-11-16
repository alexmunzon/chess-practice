#!/usr/bin/env python3
"""Prepare a private unsigned offline-study .app using installed tools only.

This script never launches, installs, registers, contacts a service or changes
permissions. It signs nothing, except the opt-in Simulator-only --mock-glasses copy,
which it ad hoc signs (no identity). Output must be a new directory outside the source checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SHA256 = "ed30d4974c39e73d64c5450a1bc1ea66359e7241e28cc5f88d6bd0299207926a"
STUDY_FIXTURES = {
    "Study/afterE4.png": ("000002.png", "4f40873feb7b4f023592669302d393f9b3cbc716aee37616ff258f942e1cf825"),
    "Study/enPassant.png": ("000034.png", "ff2f652fdec4e1fa2b754e3de35aad48995c6047fd97360e1b7940f637ae04cd"),
    "Study/promotion.png": ("000038.png", "0a340c5aaf425e35fbb744a1eb9f945ed66cf788c793ad17f41a9ac9bd3fbd88"),
    "Study/occluded.png": ("000068.png", "c02544067d3aba32b660e1093df77b0c7eac6076984c003bd2454f8c0c192f2b"),
}
# Replay game frames: byte-for-byte copies of the selected sequence (scripts/simulation/
# select-replay-sequence.mjs, 2026-11-15). Only the pixels are bundled, never the manifest or its
# evaluatorTruth section. The same SHA-256 pins are repeated in ReplayGame.swift.
REPLAY_FRAMES = {
    **{f"Replay/frame-{i:03d}.png": (f"frame-{i:03d}.png", sha) for i, sha in enumerate([
        "ed30d4974c39e73d64c5450a1bc1ea66359e7241e28cc5f88d6bd0299207926a",
        "ed30d4974c39e73d64c5450a1bc1ea66359e7241e28cc5f88d6bd0299207926a",
        "4f40873feb7b4f023592669302d393f9b3cbc716aee37616ff258f942e1cf825",
        "4f40873feb7b4f023592669302d393f9b3cbc716aee37616ff258f942e1cf825",
        "b2c518e33713679be97a7cd74d690b98c15977ab2990813442f66b57d3167db9",
        "b2c518e33713679be97a7cd74d690b98c15977ab2990813442f66b57d3167db9",
        "7e74cd459577938cc6bad8ecb2a33530b00b1ad101ea89b35243eeeb6b12005d",
        "7e74cd459577938cc6bad8ecb2a33530b00b1ad101ea89b35243eeeb6b12005d",
        "096c62ca48e04d8b8b841fd110ee21b4bc8eca57f6b9bb25e352eca10ba03b30",
        "096c62ca48e04d8b8b841fd110ee21b4bc8eca57f6b9bb25e352eca10ba03b30",
        "983b9caa9157e97877192ec5f8bf21cc783b38c689bede6c23b246a1a466b21e",
        "983b9caa9157e97877192ec5f8bf21cc783b38c689bede6c23b246a1a466b21e",
        "e7f93fb7b5b31d9ac5b662052c42c5d312eee2b8a51b4e4f57e77d09dfc3077d",
        "e7f93fb7b5b31d9ac5b662052c42c5d312eee2b8a51b4e4f57e77d09dfc3077d",
    ])},
    "Replay/interruption.png": ("frame-014.png", "c02544067d3aba32b660e1093df77b0c7eac6076984c003bd2454f8c0c192f2b"),
}
# Special-move replay game: byte-for-byte copies of scripts/simulation/generate-special-game.mjs
# output (2026-11-15, manifest SHA-256 9d1c5fc8...f3f6982b). Pixels only, never the manifest or its
# evaluatorTruth section. The same SHA-256 pins are repeated in ReplayGame.swift.
SPECIAL_REPLAY_FRAMES = {
    **{f"ReplaySpecial/frame-{i:03d}.png": (f"frame-{i:03d}.png", sha) for i, sha in enumerate([
        "725b4ef13d9a5c7b9319c5e6c90cd0a49b08e118e54261a2575104b1e35d46cb",
        "7428476f6c3d7e9f0fceda395fa5058283f8057563e193b07da1917e954e49fd",
        "d86a2b19dd44a6f69d23c98f3e9ecefc7860ad1c63a2deb028e1e487f2d48aab",
        "2ef9072cc001d98f6e526db8fcdb6ee2bba296f01efeb69db1d3933d2aa66ef3",
        "6af693ddcb578db2bf8c30f2c3ad62f27ef1d1ea3b3a58dfe7ee7635ee79fd92",
        "72c9d86d4b1cf4110ccd7bb02ed325305cd38bed1acf0a357cd98320418e2353",
        "3524a487900def0d01354c3a958de604817d83facbac30485c3f61ed22a6def5",
        "2a5b2a3d481f6b1f7cc7089365fbe3c2605dbcb58a3f685fddbcf083e36f0e21",
        "8332f6c64ece084f00787d8146c366482455acf8d9818971c5306456698711f9",
        "810a5c513bbe8157fb722c8b06d9c26fef4758674f2e04e02affe04072eb53a7",
        "b3aa16a094673e8cd52bf43ae704725b724b292d58b73421d1fe56e416f43a7b",
        "a3cbc56210a8ba480ab048aefdd8f1d75d1fa3d2a9bbd2142198377c64713d6b",
        "010511f431e43644909e6232854224084b61d2ce515de588cea9a03294d55983",
        "aaead77d0d3aa1e7492e60ad4ad4bc7779c15fc38ae330b466618c73bb265db3",
        "a9d27fab4b056200ccddcbf6b6600636bd8617dc88cce97149cae7e3f11f43cb",
        "e3f2ce69f029f5bc103200cc4e80862b25d914521645b56bcd5dbe57379dba2e",
        "f6a5baee7e025c48113a4473e9a3c67f4f59018a0add2e6e4816c2be340f5eb0",
        "10a24a4d6b96fca5d2255a7f53b8c10ce91ec520c85ff271612b1ef7eee70e85",
        "a4bc11dd13665dd13ca2d836f460ba9636363a89b44dbee7e51a29d746796560",
        "8c99079d5ed9456befdadc6d3a9a11e6ebdd7265af3ed835a2efa4089a38480b",
        "61c6aaf68e69971904d11c625a9e8cbb846a6a0df916e5e5bf3b083f7853e40a",
        "b36bbc7d516e0b1a0cc3a41f0f31f823e266959728be3239c494bd09030471d5",
        "92436aea38886a45b392692ac847fa152cac958734159a0c34f79994a8fefe0b",
        "ba7e0923174b5559bea3bf1896f6049ecff9d2d71dabb32f9001076eaf328488",
        "1214c3a1006dc919c02aaa76a4eed861bd8e27edc4f33295f107e6d14c0dc9a3",
        "3a20461a21011b00a5bc67b1969810afd11241ec99958bca7780a1bad495a3cf",
    ])},
    "ReplaySpecial/occlusion.png": ("frame-026.png", "76e6b1c0f1a1564e58c15afc9969e4f7fd324814528a243fc45edc7389c7219c"),
    "ReplaySpecial/missing-piece.png": ("frame-027.png", "9c0c9f6c0e11714d262657919c180d4937864f2666d459aed4df25e712a3e22d"),
}
ALLOWED = {
    "index.html", "runtime.js", "core/device-backend.js", "core/worker-engine.js", "core/prewarmed-engine.js",
    "core/position.js", "core/move-speech.js", "core/observation.js", "core/device-game-session.js",
    "core/replay-runtime.js", "vendor/chess.js",
    "engine/stockfish.js", "engine/stockfish.wasm", "licenses/Stockfish-Copying.txt",
    "licenses/chess.js-LICENSE", "THIRD_PARTY_NOTICES.md",
}
LOCAL_SOURCES = {
    "index.html": "native/ChessCompanionRuntime/index.html", "runtime.js": "native/ChessCompanionRuntime/runtime.js",
    **{f"core/{name}.js": f"src/core/{name}.js" for name in ["device-backend", "worker-engine", "prewarmed-engine", "position", "move-speech",
                                                                 "observation", "device-game-session", "replay-runtime"]},
    "vendor/chess.js": "node_modules/chess.js/dist/esm/chess.js",
    "engine/stockfish.js": "node_modules/stockfish/bin/stockfish-19-single.js",
    "engine/stockfish.wasm": "node_modules/stockfish/bin/stockfish-19-single.wasm",
    "licenses/Stockfish-Copying.txt": "node_modules/stockfish/Copying.txt",
    "licenses/chess.js-LICENSE": "node_modules/chess.js/LICENSE", "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
}
SOURCES = [
    "native/ChessCompanionCapture/Sources/ChessCompanionCapture/CaptureContracts.swift",
    "native/ChessCompanionVision/ImageDecoder.swift", "native/ChessCompanionVision/PixelFeatures.swift",
    "native/ChessCompanionVision/SyntheticRecognizer.swift",
    "native/ChessCompanionRuntime/NativeEngineRuntime.swift",
    "native/ChessCompanionIntegration/Adapters.swift", "native/ChessCompanionIntegration/RuntimeTransport.swift",
    "native/ChessCompanionIntegration/ReplayTracker.swift", "native/ChessCompanionIntegration/ReplayTrackerRuntimeTransport.swift",
    "native/ChessCompanionApp/OfflineStudy.swift", "native/ChessCompanionApp/ReplayGame.swift", "native/ChessCompanionApp/AppAdapters.swift",
    "native/ChessCompanionApp/ChessCompanionApp.swift",
]
SELF_TEST_SOURCE = "native/ChessCompanionApp/SelfTest.swift"
# Opt-in Simulator-only mock-glasses copy (docs/MOCK_GLASSES_RUN.md). Meta's code enters a build only
# with --mock-glasses AND --simulator; every other build is unchanged. SHA-256 of each framework
# binary as copied from the SDK 1.0.1 ios-arm64_x86_64-simulator slices (phase1/hashes.txt).
MOCK_GLASSES_FRAMEWORKS = {
    "MWDATCore": "a9bcb4fe0fd4b2b6fe16643b012cedaa5cf187e5631e279032b92258d2fa07f7",
    "MWDATCamera": "4365370e35a84f956246aa90c8b343daa661b8a93cecf7d8659021e972988a07",
    "MWDATMockDevice": "36b4fa14fee08d8d4e9db0d901ccf91a8a6e3ad6c3628d1a91ac24384e874b21",
}
# replay-14.mp4 from scripts/simulation/make-mock-glasses-video.py (HEVC hvc1 720x1280 30 fps, 30 s).
MOCK_GLASSES_VIDEO_SHA256 = "cf99c6661507c5de71fb931e2abfff1d2c4109a5520cd8e9202604bf2f3b8e87"
MOCK_GLASSES_SOURCES = [
    "native/ChessCompanionCapture/Sources/ChessCompanionCapture/CaptureCoordinator.swift",
    "native/ChessCompanionCapture/Sources/ChessCompanionCapture/IOSAdapters.swift",
    "native/ChessCompanionApp/MockGlassesSource.swift",
]
MOCK_GLASSES_URL_SCHEME = "chesscompanionmock"
MOCK_GLASSES_ENTITLEMENTS = {"application-identifier": "local.chesscompanion.offlinestudy.mockglasses",
                             "keychain-access-groups": ["local.chesscompanion.offlinestudy.mockglasses"]}
# Exactly the keys MWDATCore validates (native/MockGlassesProbe/README.md). No camera or microphone
# usage keys, no ClientToken/TeamID, MetaAppID 0 (Developer Mode), both Meta data opt-outs on.
MOCK_GLASSES_INFO = {
    "NSBluetoothAlwaysUsageDescription": "Simulator test copy: declared because Meta's SDK checks it. Not used.",
    "NSLocalNetworkUsageDescription": "Simulator test copy: declared because Meta's SDK checks it. Not used.",
    "NSBonjourServices": ["_meta-datax._tcp"],
    "UIBackgroundModes": ["bluetooth-central", "external-accessory"],
    "UISupportedExternalAccessoryProtocols": ["com.meta.ar.wearable"],
    "CFBundleURLTypes": [{"CFBundleURLName": "local.chesscompanion.offlinestudy.mockglasses",
                          "CFBundleURLSchemes": [MOCK_GLASSES_URL_SCHEME]}],
    "MWDAT": {"AppLinkURLScheme": MOCK_GLASSES_URL_SCHEME + "://", "MetaAppID": "0",
              "Analytics": {"OptOut": True}, "CrashReporting": {"OptOut": True}},
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular_file(path, maximum):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError(f"Invalid bounded regular input: {path}")
    data = path.read_bytes()
    if not 0 < len(data) <= maximum:
        raise ValueError(f"Input size changed: {path}")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--runtime-assets", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--fixture-directory", type=Path, help="Frozen corpus pixels directory for the additional study positions")
    parser.add_argument("--replay-directory", type=Path, help="Selected replay sequence pixels directory (frame-000.png ... frame-014.png) for the Replay game mode")
    parser.add_argument("--special-replay-directory", type=Path, help="Special-move game pixels directory (frame-000.png ... frame-027.png and index.json) as a second Replay game")
    parser.add_argument("--simulator", action="store_true", help="Compile for the arm64 iOS Simulator SDK")
    parser.add_argument("--self-test", action="store_true", help="Include SelfTest.swift (-D COMPANION_SELFTEST); it runs only with launch argument --chess-self-test")
    parser.add_argument("--mock-glasses", type=Path, metavar="FRAMEWORKS_DIR", help="Simulator only: link and embed Meta's mock-glasses SDK from this folder of MWDATCore/MWDATCamera/MWDATMockDevice .framework copies (pinned)")
    parser.add_argument("--mock-glasses-video", type=Path, help="With --mock-glasses: the pinned HEVC test video to bundle as MockGlasses/replay-14.mp4")
    args = parser.parse_args()
    if args.mock_glasses and not args.simulator:
        parser.error("--mock-glasses is Simulator-only and requires --simulator; device builds never contain Meta code")
    if bool(args.mock_glasses) != bool(args.mock_glasses_video):
        parser.error("--mock-glasses and --mock-glasses-video must be given together")
    if args.mock_glasses and args.self_test:
        parser.error("--mock-glasses cannot be combined with --self-test")
    if args.simulator and not args.fixture_directory:
        parser.error("--simulator requires --fixture-directory for the multi-position study")
    if args.self_test and not (args.replay_directory and args.special_replay_directory):
        parser.error("--self-test requires --replay-directory and --special-replay-directory (the self-test includes both Replay games)")
    raw = args.out.absolute()
    if any(path.is_symlink() for path in [raw, *raw.parents]):
        raise ValueError("Output cannot pass through a symbolic link")
    output = raw.resolve()
    if output == ROOT or ROOT in output.parents or output.exists():
        raise ValueError("Choose a new output directory outside the repository")
    runtime = args.runtime_assets.resolve(strict=True)
    manifest_bytes = regular_file(runtime / "runtime-manifest.json", 32 * 1024)
    manifest = json.loads(manifest_bytes)
    if manifest.get("schemaVersion") != 1 or manifest.get("mode") != "private-on-device-runtime-assets" or manifest.get("entry") != "index.html" or set(manifest.get("assets", {})) != ALLOWED or manifest.get("versions") != {"stockfish": "19.0.1", "chess.js": "1.4.0"}:
        raise ValueError("Unexpected local engine manifest")
    lock = json.loads(regular_file(ROOT / "package-lock.json", 1024 * 1024))
    for package, version in {"stockfish": "19.0.1", "chess.js": "1.4.0"}.items():
        installed = json.loads(regular_file(ROOT / "node_modules" / package / "package.json", 1024 * 1024))
        if installed.get("version") != version or lock.get("packages", {}).get("node_modules/" + package, {}).get("version") != version or lock.get("packages", {}).get("", {}).get("dependencies", {}).get(package) != version:
            raise ValueError(f"Unexpected pinned local dependency: {package}")
    # Validate all bytes before creating output; copy exactly these verified bytes.
    runtime_bytes = {}
    for name in sorted(ALLOWED):
        file = runtime / name
        if runtime not in file.resolve(strict=True).parents:
            raise ValueError("Engine asset escaped input root")
        data = regular_file(file, 128 * 1024 * 1024)
        expected = manifest["assets"][name]
        mime = "text/javascript" if name.endswith(".js") else "application/wasm" if name.endswith(".wasm") else "text/html" if name.endswith(".html") else "text/plain"
        if expected.get("mimeType") != mime:
            raise ValueError(f"Unexpected engine asset MIME: {name}")
        source = regular_file(ROOT / LOCAL_SOURCES[name], 128 * 1024 * 1024)
        transformed = source.replace(b"from 'chess.js'", b"from '../vendor/chess.js'") if name == "core/position.js" else source
        if expected.get("source") != LOCAL_SOURCES[name] or expected.get("sourceSha256") != digest(source) or transformed != data:
            raise ValueError(f"Runtime asset differs from current pinned local source: {name}")
        if len(data) != expected.get("byteLength") or digest(data) != expected.get("sha256"):
            raise ValueError(f"Engine asset hash/size mismatch: {name}")
        runtime_bytes[name] = data
    fixture = regular_file(args.fixture, 8 * 1024 * 1024)
    if digest(fixture) != FIXTURE_SHA256:
        raise ValueError("Only the recorded owned synthetic starting-frame fixture is accepted")
    fixtures = {"synthetic-fixture.png": fixture}
    if args.fixture_directory:
        for name, (filename, expected) in STUDY_FIXTURES.items():
            data = regular_file(args.fixture_directory / filename, 8 * 1024 * 1024)
            if digest(data) != expected:
                raise ValueError(f"Unexpected owned synthetic fixture: {filename}")
            fixtures[name] = data
    for directory, pinned, last in [(args.replay_directory, REPLAY_FRAMES, "frame-014.png"),
                                    (args.special_replay_directory, SPECIAL_REPLAY_FRAMES, "frame-027.png")]:
        if not directory:
            continue
        names = sorted(path.name for path in directory.iterdir())
        expected_names = sorted([filename for filename, _ in pinned.values()] + ["index.json"])
        if names != expected_names:
            raise ValueError(f"Replay directory must contain exactly frame-000.png ... {last} and index.json: {directory}")
        for name, (filename, expected) in pinned.items():
            data = regular_file(directory / filename, 8 * 1024 * 1024)
            if digest(data) != expected:
                raise ValueError(f"Unexpected replay frame: {directory / filename}")
            fixtures[name] = data
    template = regular_file(ROOT / "native/ChessCompanionVision/Assets/classic-templates-v1.json", 512 * 1024)
    sources = SOURCES + ([SELF_TEST_SOURCE] if args.self_test else []) + (MOCK_GLASSES_SOURCES if args.mock_glasses else [])
    mock_frameworks = {}
    if args.mock_glasses:
        root = args.mock_glasses.resolve(strict=True)
        for name, expected in MOCK_GLASSES_FRAMEWORKS.items():
            folder = root / f"{name}.framework"
            if folder.is_symlink() or not folder.is_dir() or any(path.is_symlink() for path in folder.rglob("*")):
                raise ValueError(f"Mock-glasses framework must be a real folder without links: {folder}")
            if digest(regular_file(folder / name, 64 * 1024 * 1024)) != expected:
                raise ValueError(f"Mock-glasses framework binary does not match its pinned SHA-256: {folder / name}")
            mock_frameworks[name] = folder
        mock_video = regular_file(args.mock_glasses_video, 16 * 1024 * 1024)
        if digest(mock_video) != MOCK_GLASSES_VIDEO_SHA256:
            raise ValueError("Mock-glasses video does not match its pinned SHA-256")
    source_bytes = {name: regular_file(ROOT / name, 1024 * 1024) for name in sources}
    swiftc = subprocess.check_output(["xcrun", "--find", "swiftc"], text=True).strip()
    sdk_name = "iphonesimulator" if args.simulator else "iphoneos"
    target_triple = "arm64-apple-ios17.2-simulator" if args.simulator else "arm64-apple-ios17.2"
    sdk = subprocess.check_output(["xcrun", "--sdk", sdk_name, "--show-sdk-path"], text=True).strip()
    output.mkdir(parents=True)
    for name, data in source_bytes.items():
        snapshot = output / "sources" / name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(data)
    app = output / "ChessCompanion.app"
    app.mkdir()
    for name, data in runtime_bytes.items():
        target = app / "Runtime" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (app / "Runtime/runtime-manifest.json").write_bytes(manifest_bytes)
    for name, data in fixtures.items():
        asset = app / name
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(data)
    (app / "classic-templates-v1.json").write_bytes(template)
    if args.mock_glasses:
        # Kept OUT of app-assets.json (StudyResources accepts only known asset groups); MockGlassesSource.swift
        # re-verifies this file against its own SHA-256 constant before feeding it to the mock glasses.
        (app / "MockGlasses").mkdir()
        (app / "MockGlasses" / "replay-14.mp4").write_bytes(mock_video)
    resources = {**fixtures, "classic-templates-v1.json": template, "Runtime/runtime-manifest.json": manifest_bytes}
    app_manifest = {"schemaVersion": 1, "mode": "private-unsigned-offline-synthetic-study", "assets": {
        name: {"byteLength": len(data), "sha256": digest(data)} for name, data in resources.items()}}
    (app / "app-assets.json").write_text(json.dumps(app_manifest, indent=2) + "\n")
    info = {"CFBundleIdentifier": "local.chesscompanion.offlinestudy", "CFBundleExecutable": "ChessCompanion",
            "CFBundleName": "Chess Companion", "CFBundleDisplayName": "Chess Companion",
            "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "0.1.0", "CFBundleVersion": "1",
            "MinimumOSVersion": "17.2", "LSRequiresIPhoneOS": True, "UIDeviceFamily": [1],
            "CFBundleSupportedPlatforms": ["iPhoneSimulator" if args.simulator else "iPhoneOS"],
            "UIApplicationSceneManifest": {"UIApplicationSupportsMultipleScenes": False}, "UILaunchScreen": {},
            "UISupportedInterfaceOrientations": ["UIInterfaceOrientationPortrait", "UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight"]}
    if args.simulator:
        info["CFBundleIdentifier"] = "local.chesscompanion.offlinestudy.simulator"
        info.pop("LSRequiresIPhoneOS")
    if args.mock_glasses:
        info["CFBundleIdentifier"] = "local.chesscompanion.offlinestudy.mockglasses"
        info["CFBundleDisplayName"] = "Chess Mock Glasses"
        info.update(MOCK_GLASSES_INFO)
        if {"NSCameraUsageDescription", "NSMicrophoneUsageDescription"} & set(info):
            raise ValueError("Mock-glasses copy must not declare camera or microphone usage")
    (app / "Info.plist").write_bytes(plistlib.dumps(info))
    (app / "OFFLINE-STUDY-NOTICE.txt").write_text(
        "Private development artifact. Offline known-template study only.\n"
        "No live camera, microphone, Bluetooth, Meta registration or capture timestamp.\n"
        "Owned synthetic images: generated 2026-11-11 by scripts/simulation/render.py\n"
        "(special-move replay game: 2026-11-15, scripts/simulation/generate-special-game.mjs).\n"
        "Engine GPL notices and chess.js license are preserved in Runtime/.\n"
        "Do not distribute until corresponding-source delivery obligations are verified.\n")
    # -O: optimized build. Without it swiftc defaults to -Onone (debug code), the main measured cause
    # of the slow pixel recognizer. -O does not enable fast-math, so recognizer decisions are unchanged.
    command = [swiftc, "-parse-as-library", "-swift-version", "6", "-O", "-target", target_triple, "-sdk", sdk,
               "-D", "COMPANION_MONOLITHIC_BUILD", "-D", "COMPANION_RUNTIME_SOURCE", *(["-D", "COMPANION_SELFTEST"] if args.self_test else []),
               "-module-cache-path", str(output / "module-cache"), "-emit-executable",
               "-Xlinker", "-no_adhoc_codesign", "-o", str(app / "ChessCompanion"), *[str(output / "sources" / p) for p in sources]]
    if args.mock_glasses:
        import shutil
        for name, folder in mock_frameworks.items():
            shutil.copytree(folder, app / "Frameworks" / f"{name}.framework", symlinks=False)
            if digest((app / "Frameworks" / f"{name}.framework" / name).read_bytes()) != MOCK_GLASSES_FRAMEWORKS[name]:
                raise ValueError(f"Embedded framework changed while copying: {name}")
        # Simulator keychain access (used by MWDATCore.configure) needs simulated entitlements. As Xcode does for
        # Simulator builds, they go only in an __entitlements section (not in the ad hoc signature, which the host
        # would refuse to launch). No identity, account or provisioning.
        entitlements = output / "mock-glasses.entitlements"
        entitlements.write_bytes(plistlib.dumps(MOCK_GLASSES_ENTITLEMENTS))
        command[-len(sources):-len(sources)] = [
            "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT", "-Xlinker", "__entitlements", "-Xlinker", str(entitlements),
            "-D", "COMPANION_MOCK_GLASSES", "-F", str(app / "Frameworks"),
            *[flag for name in MOCK_GLASSES_FRAMEWORKS for flag in ("-framework", name)],
            "-Xlinker", "-rpath", "-Xlinker", "@executable_path/Frameworks"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=180)
    (output / "compile.stdout.txt").write_bytes(completed.stdout)
    (output / "compile.stderr.txt").write_bytes(completed.stderr)
    report = {"schemaVersion": 1, "mode": "direct-unsigned-ios-app-assembly", "app": str(app),
              "target": target_triple, "selfTest": args.self_test, "command": command, "exitCode": completed.returncode, "sourceSha256": {p: digest(data) for p, data in source_bytes.items()},
              "runtimeManifestSha256": digest(manifest_bytes), "fixtureSha256": digest(fixture), "appAssets": app_manifest,
              "replayFramesBundled": bool(args.replay_directory),
              "specialReplayFramesBundled": bool(args.special_replay_directory), "evaluatorTruthBundled": False,
              "executed": False, "installed": False, "signed": False, "deviceVerified": False, "audibleSpeechVerified": False}
    if args.mock_glasses:
        report["mockGlasses"] = {"frameworkSha256": MOCK_GLASSES_FRAMEWORKS, "videoSha256": MOCK_GLASSES_VIDEO_SHA256,
                                 "bundleIdentifier": info["CFBundleIdentifier"], "simulatorOnly": True}
    if completed.returncode == 0:
        binary = app / "ChessCompanion"
        report["binarySha256"] = digest(binary.read_bytes())
        inspected = subprocess.run(["otool", "-l", str(binary)], capture_output=True, text=True, check=True)
        (output / "binary-load-commands.txt").write_text(inspected.stdout)
        if "LC_CODE_SIGNATURE" in inspected.stdout:
            raise ValueError("Unexpected code signature; no signing operation was requested")
        if args.mock_glasses:
            # Simulator-only ad hoc signing (no identity, account or entitlements): frameworks first, then the app.
            for name in MOCK_GLASSES_FRAMEWORKS:
                subprocess.run(["codesign", "--force", "--sign", "-", str(app / "Frameworks" / f"{name}.framework")], check=True, capture_output=True)
            subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True, capture_output=True)
            subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True, capture_output=True)
            report["signed"] = "ad-hoc (Simulator only)"
            report["signedBinarySha256"] = digest(binary.read_bytes())
            # Pins above are for the unsigned SDK binaries; ad hoc signing rewrites the embedded copies.
            report["mockGlasses"]["embeddedFrameworkSha256AfterSigning"] = {
                name: digest((app / "Frameworks" / f"{name}.framework" / name).read_bytes()) for name in MOCK_GLASSES_FRAMEWORKS}
    (output / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"app": str(app), "exitCode": completed.returncode, "executed": False, "signed": report["signed"]}))
    return completed.returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
