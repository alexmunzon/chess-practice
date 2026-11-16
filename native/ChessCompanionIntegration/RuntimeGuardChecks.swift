// macOS checks of NativeEngineRuntime's request guards, compiled together with NativeEngineRuntime.swift.
// Construction only: no WKWebView is created, no page is loaded and nothing is executed in WebKit.
// Usage: RuntimeGuardChecks RUNTIME_ASSET_DIRECTORY   (a bundle built by scripts/build-device-runtime.mjs)
#if os(macOS)
import Foundation

private struct CheckFailed: Error { let message: String }
private func require(_ condition: Bool, _ message: String) throws { if !condition { throw CheckFailed(message: message) } }

@main @MainActor struct RuntimeGuardChecks {
    static func main() {
        guard CommandLine.arguments.count == 2 else { print("Usage: RuntimeGuardChecks RUNTIME_ASSET_DIRECTORY"); exit(2) }
        let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let checks: [(String, @MainActor () throws -> Void)] = [
            ("exactly two prewarm kinds were added to the engine kinds", {
                try require(NativeEngineRuntime.engineKinds == ["position", "move", "analyze", "cancel", "prewarm", "cancelPrewarm"], "engine kinds changed")
                try require(NativeEngineRuntime.trackerKinds == ["initialize", "observe", "invalidate", "snapshot"], "tracker kinds changed")
                for kind in ["warmup", "go", "Prewarm", "bestmove", ""] { try require(!NativeEngineRuntime.engineKinds.contains(kind), "unknown kind accepted: \(kind)") }
            }),
            ("a prewarm never supersedes a pending real request (engine or tracker)", {
                let real = NativeEngineRuntime.trackerKinds.union(["position", "move", "analyze", "cancel"])
                for pending in real {
                    for kind in ["prewarm", "cancelPrewarm"] {
                        try require(!NativeEngineRuntime.mayReplace(pendingKind: pending, with: kind), "\(kind) may replace pending \(pending)")
                    }
                }
                for pending in ["prewarm", "cancelPrewarm"] {
                    for kind in ["prewarm", "cancelPrewarm"] { try require(NativeEngineRuntime.mayReplace(pendingKind: pending, with: kind), "\(kind) blocked by pending \(pending)") }
                }
                for kind in real.union(["prewarm", "cancelPrewarm"]) { try require(NativeEngineRuntime.mayReplace(pendingKind: nil, with: kind), "\(kind) blocked with nothing pending") }
                // Real requests keep superseding anything (unchanged single-pending behaviour).
                for kind in real { for pending in real.union(["prewarm", "cancelPrewarm"]) { try require(NativeEngineRuntime.mayReplace(pendingKind: pending, with: kind), "\(kind) blocked by \(pending)") } }
            }),
            ("the asset manifest must be exactly the 16 allowed assets", {
                let manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("runtime-manifest.json"))) as! [String: Any]
                @MainActor func refused(_ edit: (inout [String: Any]) -> Void) throws -> Bool {
                    let temp = FileManager.default.temporaryDirectory.appendingPathComponent("runtime-guard-\(UUID().uuidString)", isDirectory: true)
                    defer { try? FileManager.default.removeItem(at: temp) }
                    try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
                    var copy = manifest, assets = manifest["assets"] as! [String: Any]
                    edit(&assets); copy["assets"] = assets
                    try JSONSerialization.data(withJSONObject: copy).write(to: temp.appendingPathComponent("runtime-manifest.json"))
                    do { _ = try NativeEngineRuntime(resourceDirectory: temp); return false } catch { return true }
                }
                try require(try !refused { _ in }, "the real manifest was refused")
                try require(try refused { $0["core/unknown.js"] = $0["runtime.js"] }, "an unknown asset was accepted")
                try require(try refused { $0.removeValue(forKey: "core/prewarmed-engine.js") }, "the 15-asset manifest was accepted")
            }),
        ]
        var failures = 0
        for (name, check) in checks {
            do { try check(); print("PASS: \(name)") } catch { failures += 1; print("FAIL: \(name): \(error)") }
        }
        print("\(checks.count - failures)/\(checks.count) runtime guard checks passed; construction only, no WebKit execution.")
        exit(failures == 0 ? 0 : 1)
    }
}
#endif
