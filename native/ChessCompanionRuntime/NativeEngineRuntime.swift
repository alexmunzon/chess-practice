import Foundation
import CryptoKit
import WebKit

public enum NativeEngineRuntimeError: Error, LocalizedError {
    case unavailable(String), cancelled, timedOut, invalidReply
    public var errorDescription: String? {
        switch self {
        case .unavailable(let message): return message
        case .cancelled: return "Local engine request cancelled."
        case .timedOut: return "Local engine deadline exceeded."
        case .invalidReply: return "Invalid local engine reply."
        }
    }
}

private struct RuntimeManifest: Decodable {
    struct Asset: Decodable {
        let mimeType: String
        let byteLength: Int
        let sha256: String
    }
    let schemaVersion: Int
    let mode: String
    let entry: String
    let assets: [String: Asset]
}

@MainActor
private final class LocalRuntimeAssets: NSObject, WKURLSchemeHandler {
    static let allowed: Set<String> = ["index.html", "runtime.js", "core/device-backend.js", "core/worker-engine.js", "core/position.js", "core/move-speech.js", "core/observation.js", "core/device-game-session.js", "core/replay-runtime.js", "vendor/chess.js", "engine/stockfish.js", "engine/stockfish.wasm", "licenses/Stockfish-Copying.txt", "licenses/chess.js-LICENSE", "THIRD_PARTY_NOTICES.md"]
    private let root: URL
    private let manifest: RuntimeManifest
    init(directory: URL) throws {
        root = directory.standardizedFileURL.resolvingSymlinksInPath()
        guard root.isFileURL else { throw NativeEngineRuntimeError.unavailable("Local runtime directory required.") }
        let manifestFile = root.appendingPathComponent("runtime-manifest.json").resolvingSymlinksInPath()
        guard manifestFile.path.hasPrefix(root.path + "/") else { throw NativeEngineRuntimeError.unavailable("Manifest escaped runtime directory.") }
        let attributes = try FileManager.default.attributesOfItem(atPath: manifestFile.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
              let length = (attributes[.size] as? NSNumber)?.intValue, (1...32 * 1024).contains(length) else { throw NativeEngineRuntimeError.unavailable("Invalid runtime manifest file.") }
        let bytes = try Data(contentsOf: manifestFile)
        guard bytes.count <= 32 * 1024 else { throw NativeEngineRuntimeError.unavailable("Runtime manifest exceeded limit.") }
        manifest = try JSONDecoder().decode(RuntimeManifest.self, from: bytes)
        guard manifest.schemaVersion == 1, manifest.mode == "private-on-device-runtime-assets", manifest.entry == "index.html", Set(manifest.assets.keys) == Self.allowed else {
            throw NativeEngineRuntimeError.unavailable("Unexpected runtime asset manifest.")
        }
        for (path, asset) in manifest.assets {
            let expectedMime = path.hasSuffix(".js") ? "text/javascript" : path.hasSuffix(".wasm") ? "application/wasm" : path.hasSuffix(".html") ? "text/html" : "text/plain"
            guard asset.mimeType == expectedMime, asset.byteLength > 0, asset.byteLength <= 128 * 1024 * 1024,
                  asset.sha256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else {
                throw NativeEngineRuntimeError.unavailable("Invalid runtime asset metadata.")
            }
        }
        super.init()
    }
    func webView(_ webView: WKWebView, start urlSchemeTask: any WKURLSchemeTask) {
        do {
            guard let url = urlSchemeTask.request.url, url.scheme == "chess-local", url.host == "bundle",
                  url.user == nil, url.password == nil, url.port == nil, url.query == nil, url.fragment == nil,
                  urlSchemeTask.request.httpMethod == "GET" else { throw NativeEngineRuntimeError.invalidReply }
            let path = String(url.path.dropFirst())
            guard Self.allowed.contains(path), let asset = manifest.assets[path] else { throw NativeEngineRuntimeError.invalidReply }
            let file = root.appendingPathComponent(path).standardizedFileURL.resolvingSymlinksInPath()
            guard file.path.hasPrefix(root.path + "/") else { throw NativeEngineRuntimeError.invalidReply }
            let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
            guard attributes[.type] as? FileAttributeType == .typeRegular,
                  (attributes[.size] as? NSNumber)?.intValue == asset.byteLength else { throw NativeEngineRuntimeError.invalidReply }
            let data = try Data(contentsOf: file, options: .mappedIfSafe)
            guard data.count == asset.byteLength, SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == asset.sha256 else { throw NativeEngineRuntimeError.invalidReply }
            let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: ["Content-Type":asset.mimeType, "Content-Length":String(data.count), "Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"])!
            urlSchemeTask.didReceive(response)
            urlSchemeTask.didReceive(data)
            urlSchemeTask.didFinish()
        } catch { urlSchemeTask.didFailWithError(error) }
    }
    func webView(_ webView: WKWebView, stop urlSchemeTask: any WKURLSchemeTask) {}
}

@MainActor
private final class RuntimeMessageRelay: NSObject, WKScriptMessageHandler {
    weak var owner: NativeEngineRuntime?
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) { owner?.receive(message) }
}

/// An explicit, nonpersistent in-process WebKit host. No Mac server, browser
/// profile, network endpoint, device registration, capture or speech operation.
/// Compilation alone does not establish WebKit or iPhone runtime compatibility.
@MainActor
public final class NativeEngineRuntime: NSObject, WKNavigationDelegate {
    private struct Pending {
        let transportId: String
        let requestId: String
        let kind: String
        let tracker: Bool
        let deadline: ContinuousClock.Instant
        let continuation: CheckedContinuation<String, any Error>
    }
    private let assets: LocalRuntimeAssets
    private let relay = RuntimeMessageRelay()
    private var webView: WKWebView?
    private var pending: Pending?
    private var readyContinuation: CheckedContinuation<Void, any Error>?
    private var deadlineTask: Task<Void, Never>?
    private var startupTask: Task<Void, Never>?
    private let clock = ContinuousClock()
    private var readyDeadline: ContinuousClock.Instant?
    private var closed = false
    public private(set) var isReady = false
    /// Called once, on the main actor, the first time the runtime closes (explicit close or failure).
    public var onClose: (@MainActor () -> Void)?
    /// Local legal-move engine commands (unchanged). They never carry a `mode` key.
    public static let engineKinds: Set<String> = ["position", "move", "analyze", "cancel"]
    /// Replay-tracker commands (docs/REPLAY_GAME.md); always `mode:"trusted-replay"`. The JS
    /// runtime routes them to its single ReplayRuntime, never to the engine backend.
    public static let trackerKinds: Set<String> = ["initialize", "observe", "invalidate", "snapshot"]
    private static func isFalseBoolean(_ value: Any?) -> Bool {
        guard let number = value as? NSNumber else { return false }
        return CFGetTypeID(number) == CFBooleanGetTypeID() && !number.boolValue
    }
    public init(resourceDirectory: URL) throws {
        assets = try LocalRuntimeAssets(directory: resourceDirectory)
        super.init()
        relay.owner = self
    }
    public func start(timeoutMilliseconds: Int = 30_000) async throws {
        guard !closed, webView == nil, (1...60_000).contains(timeoutMilliseconds) else { throw NativeEngineRuntimeError.unavailable("Runtime already started, closed, or invalid deadline.") }
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        // This engine view is detached from every window, including during an active search.
        configuration.preferences.inactiveSchedulingPolicy = .none
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.setURLSchemeHandler(assets, forURLScheme: "chess-local")
        configuration.userContentController.add(relay, name: "chessRuntime")
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.isInspectable = false
        view.navigationDelegate = self
        webView = view
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                readyContinuation = continuation
                readyDeadline = clock.now.advanced(by: .milliseconds(timeoutMilliseconds))
                startupTask = Task { [weak self] in
                    do { try await Task.sleep(nanoseconds: UInt64(timeoutMilliseconds) * 1_000_000) }
                    catch { return }
                    self?.failRuntime(NativeEngineRuntimeError.timedOut)
                }
                view.load(URLRequest(url: URL(string: "chess-local://bundle/index.html")!))
                if Task.isCancelled { failRuntime(NativeEngineRuntimeError.cancelled) }
            }
        } onCancel: { Task { @MainActor [weak self] in self?.failRuntime(NativeEngineRuntimeError.cancelled) } }
    }
    public func submit(commandJSON: String, timeoutMilliseconds: Int = 15_000) async throws -> String {
        try Task.checkCancellation()
        guard isReady, !closed, let view = webView, (1...60_000).contains(timeoutMilliseconds), commandJSON.utf8.count <= 16_384,
              let bytes = commandJSON.data(using: .utf8), let command = try JSONSerialization.jsonObject(with: bytes) as? [String:Any],
              let requestId = command["requestId"] as? String, requestId.range(of: "^[A-Za-z0-9_.:/-]{1,128}$", options: .regularExpression) != nil,
              let kind = command["kind"] as? String,
              Self.engineKinds.contains(kind) && command["mode"] == nil ||
              Self.trackerKinds.contains(kind) && command["mode"] as? String == "trusted-replay" else { throw NativeEngineRuntimeError.unavailable("Runtime not ready or command invalid.") }
        let tracker = Self.trackerKinds.contains(kind)
        // Single pending request: a tracker request supersedes (cancels) any engine analysis and vice versa.
        cancel()
        let transportId = UUID().uuidString
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                pending = Pending(transportId: transportId, requestId: requestId, kind: kind, tracker: tracker, deadline: clock.now.advanced(by: .milliseconds(timeoutMilliseconds)), continuation: continuation)
                deadlineTask = Task { [weak self] in
                    do { try await Task.sleep(nanoseconds: UInt64(timeoutMilliseconds) * 1_000_000) }
                    catch { return }
                    guard self?.pending?.transportId == transportId else { return }
                    self?.cancel(error: NativeEngineRuntimeError.timedOut)
                }
                if let current = pending, clock.now >= current.deadline { cancel(error: NativeEngineRuntimeError.timedOut); return }
                view.callAsyncJavaScript("globalThis.chessDeviceRuntime.submit(commandJSON, transportId);", arguments: ["commandJSON":commandJSON, "transportId":transportId], in: nil, in: .page) { [weak self] result in
                    guard case .failure(let error) = result, self?.pending?.transportId == transportId else { return }
                    self?.cancel(error: error)
                }
                if Task.isCancelled, pending?.transportId == transportId { cancel() }
            }
        } onCancel: { Task { @MainActor [weak self] in if self?.pending?.transportId == transportId { self?.cancel() } } }
    }
    public func cancel() { cancel(error: NativeEngineRuntimeError.cancelled) }
    private func cancel(error: any Error) {
        let previous = pending
        pending = nil
        deadlineTask?.cancel(); deadlineTask = nil
        previous?.continuation.resume(throwing: error)
        if isReady { webView?.evaluateJavaScript("globalThis.chessDeviceRuntime?.cancel();", completionHandler: nil) }
    }
    public func close() { failRuntime(NativeEngineRuntimeError.cancelled) }
    private func failRuntime(_ error: any Error) {
        let wasClosed = closed
        closed = true; isReady = false
        let initial = readyContinuation; readyContinuation = nil; readyDeadline = nil
        startupTask?.cancel(); startupTask = nil
        initial?.resume(throwing: error)
        cancel(error: error)
        webView?.evaluateJavaScript("globalThis.chessDeviceRuntime?.shutdown();", completionHandler: nil)
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: "chessRuntime")
        webView?.stopLoading(); webView?.navigationDelegate = nil
        webView = nil
        if !wasClosed { onClose?() }
    }
    fileprivate func receive(_ message: WKScriptMessage) {
        guard !closed, message.name == "chessRuntime", message.frameInfo.isMainFrame,
              message.frameInfo.securityOrigin.protocol == "chess-local", message.frameInfo.securityOrigin.host == "bundle",
              let text = message.body as? String, text.utf8.count <= 128 * 1024,
              let bytes = text.data(using: .utf8), let envelope = try? JSONSerialization.jsonObject(with: bytes) as? [String:Any],
              envelope["protocolVersion"] as? Int == 1, let kind = envelope["kind"] as? String else { failRuntime(NativeEngineRuntimeError.invalidReply); return }
        if kind == "ready" {
            guard !isReady, let initial = readyContinuation, let deadline = readyDeadline else { failRuntime(NativeEngineRuntimeError.invalidReply); return }
            guard clock.now < deadline else { failRuntime(NativeEngineRuntimeError.timedOut); return }
            readyContinuation = nil; readyDeadline = nil; startupTask?.cancel(); startupTask = nil; isReady = true
            initial.resume()
            return
        }
        if kind == "fatal" { failRuntime(NativeEngineRuntimeError.unavailable("Local engine initialization failed.")); return }
        guard kind == "reply", let transportId = envelope["transportId"] as? String else { failRuntime(NativeEngineRuntimeError.invalidReply); return }
        guard let current = pending, current.transportId == transportId else { return } // Old callback cannot settle a newer request, even with reused caller IDs.
        guard clock.now < current.deadline else { cancel(error: NativeEngineRuntimeError.timedOut); return }
        if envelope["ok"] as? Bool == false {
            let detail = envelope["error"] as? [String:Any]
            cancel(error: NativeEngineRuntimeError.unavailable(String((detail?["message"] as? String ?? "Local engine failed.").prefix(512))))
            return
        }
        guard envelope["ok"] as? Bool == true, let result = envelope["result"] as? [String:Any],
              result["requestId"] as? String == current.requestId, result["kind"] as? String == current.kind,
              result["schemaVersion"] as? Int == 1, result["runtime"] as? String == "on-device-local",
              // Tracker replies (success or structured error) must also stay replay-only with guidance denied.
              !current.tracker || result["mode"] as? String == "replay-only" && Self.isFalseBoolean(result["guidanceAllowed"]) && Self.isFalseBoolean(result["liveGuidanceAllowed"]),
              JSONSerialization.isValidJSONObject(result), let resultBytes = try? JSONSerialization.data(withJSONObject: result),
              resultBytes.count <= 128 * 1024, let resultText = String(data: resultBytes, encoding: .utf8) else { failRuntime(NativeEngineRuntimeError.invalidReply); return }
        guard clock.now < current.deadline else { cancel(error: NativeEngineRuntimeError.timedOut); return }
        pending = nil; deadlineTask?.cancel(); deadlineTask = nil
        current.continuation.resume(returning: resultText)
    }
    public func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
        let url = navigationAction.request.url
        decisionHandler(!closed && navigationAction.targetFrame?.isMainFrame == true && url?.absoluteString == "chess-local://bundle/index.html" ? .allow : .cancel)
    }
    public func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: any Error) { failRuntime(error) }
    public func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: any Error) { failRuntime(error) }
    public func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { failRuntime(NativeEngineRuntimeError.unavailable("Local engine WebKit process terminated.")) }
}
