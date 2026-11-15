// OPTIONAL OFFLINE MACOS HARNESS. Compile-only preparation is not authorization
// to execute WebKit. Run only after the user explicitly approves this harness.
#if os(macOS)
import AppKit
import Foundation
import Darwin

@main
struct VerifyRuntime {
    @MainActor
    static func main() {
        guard CommandLine.arguments.count == 2 else {
            print("Usage: VerifyRuntime GENERATED_ASSET_DIRECTORY"); exit(2)
        }
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        Task { @MainActor in
            do { try await Task.sleep(nanoseconds: 60_000_000_000) }
            catch { return }
            print("{\"passed\":false,\"error\":\"Whole offline harness exceeded 60 seconds.\"}")
            exit(1)
        }
        Task { @MainActor in
            var runtime: NativeEngineRuntime?
            let started = ProcessInfo.processInfo.systemUptime
            do {
                runtime = try NativeEngineRuntime(resourceDirectory: URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true))
                let host = runtime!
                try await host.start(timeoutMilliseconds: 30_000)
                let fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
                func command(_ value: [String:Any]) throws -> String {
                    String(data: try JSONSerialization.data(withJSONObject: value), encoding: .utf8)!
                }
                let setup = try await host.submit(commandJSON: command(["schemaVersion":1,"requestId":"position-fixture","kind":"position","fen":fen]))
                let setupJSON = try JSONSerialization.jsonObject(with: Data(setup.utf8)) as! [String:Any]
                guard (setupJSON["position"] as? [String:Any])?["fen"] as? String == fen else { throw NativeEngineRuntimeError.invalidReply }
                // Replay tracker through the same host: initialize then snapshot, routed to ReplayRuntime only.
                let replaySession: [String:Any] = ["sessionId":"macos-webkit-replay","epoch":1]
                let reviewed: [String:Any] = ["pieces":true,"turn":true,"castling":true,"enPassant":true,"counters":true]
                let initialize: [String:Any] = ["schemaVersion":1,"requestId":"replay-initialize","kind":"initialize","mode":"trusted-replay","clockDomain":"replay-synthetic-v1","session":replaySession,"fen":fen,"reviewed":reviewed]
                let initialized = try JSONSerialization.jsonObject(with: Data(try await host.submit(commandJSON: command(initialize), timeoutMilliseconds: 2_000).utf8)) as! [String:Any]
                guard initialized["error"] == nil, initialized["mode"] as? String == "replay-only", initialized["guidanceAllowed"] as? Bool == false,
                      initialized["trackingReady"] as? Bool == false, (initialized["state"] as? [String:Any])?["fen"] as? String == fen else { throw NativeEngineRuntimeError.invalidReply }
                let snapshot: [String:Any] = ["schemaVersion":1,"requestId":"replay-snapshot","kind":"snapshot","mode":"trusted-replay","clockDomain":"replay-synthetic-v1","session":replaySession]
                let snapped = try JSONSerialization.jsonObject(with: Data(try await host.submit(commandJSON: command(snapshot), timeoutMilliseconds: 2_000).utf8)) as! [String:Any]
                guard snapped["error"] == nil, snapped["kind"] as? String == "snapshot", (snapped["state"] as? [String:Any])?["status"] as? String == "stabilizing" else { throw NativeEngineRuntimeError.invalidReply }
                let identity: [String:Any] = ["sessionId":"macos-webkit-replay","epoch":1,"sequence":1,"frameSha256":String(repeating:"a",count:64),"revision":1]
                let request: [String:Any] = ["schemaVersion":1,"requestId":"analysis-fixture","kind":"analyze","fen":fen,"confirmation":true,"movetimeMs":100,"identity":identity]
                let analyzed = try await host.submit(commandJSON: command(request), timeoutMilliseconds: 15_000)
                let result = try JSONSerialization.jsonObject(with: Data(analyzed.utf8)) as! [String:Any]
                guard result["fen"] as? String == fen, let move = result["bestMove"] as? [String:Any], move["san"] is String, result["speechText"] is String else { throw NativeEngineRuntimeError.invalidReply }
                var cancellation = request; cancellation["requestId"] = "cancel-fixture"; cancellation["movetimeMs"] = 3000
                let cancelJSON = try command(cancellation)
                let pending = Task { @MainActor in try await host.submit(commandJSON: cancelJSON) }
                try await Task.sleep(nanoseconds: 20_000_000)
                host.cancel()
                do { _ = try await pending.value; throw NativeEngineRuntimeError.unavailable("Cancellation returned a result.") }
                catch NativeEngineRuntimeError.cancelled {}
                let report: [String:Any] = ["passed":true,"mode":"macos-offline-webkit-engine-fixture","iPhoneVerified":false,"glassesVerified":false,"audibleSpeechVerified":false,"existingBrowserProfilesAccessed":false,"elapsedMs":(ProcessInfo.processInfo.systemUptime-started)*1000,"position":setupJSON,"replayTracker":snapped,"analysis":result,"cancellation":"passed"]
                host.close()
                print(String(data:try JSONSerialization.data(withJSONObject:report,options:[.sortedKeys]),encoding:.utf8)!)
                exit(0)
            } catch {
                runtime?.close()
                let report: [String:Any] = ["passed":false,"mode":"macos-offline-webkit-engine-fixture","error":error.localizedDescription]
                if let data = try? JSONSerialization.data(withJSONObject:report), let text = String(data:data,encoding:.utf8) { print(text) }
                exit(1)
            }
        }
        app.run()
    }
}
#endif
