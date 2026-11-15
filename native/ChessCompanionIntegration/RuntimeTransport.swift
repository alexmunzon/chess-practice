#if COMPANION_RUNTIME_SOURCE || canImport(ChessCompanionRuntime)
import Foundation
#if canImport(ChessCompanionRuntime)
import ChessCompanionRuntime
#endif

/// A dormant wrapper around an explicitly constructed/started local runtime.
/// No start(), WKWebView construction, registration, capture or speech occurs here.
@MainActor public final class NativeRuntimeTransport: LocalJSONTransport {
    private let runtime: NativeEngineRuntime
    private var current: (operation: UUID, task: Task<String, Error>)?
    public init(runtime: NativeEngineRuntime) { self.runtime = runtime }
    public func submit(commandJSON: String, operation: UUID, timeoutMilliseconds: Int) async throws -> String {
        try Task.checkCancellation()
        current?.task.cancel()
        let runtime = self.runtime
        let task = Task { @MainActor in
            try Task.checkCancellation()
            return try await runtime.submit(commandJSON: commandJSON, timeoutMilliseconds: timeoutMilliseconds)
        }
        current = (operation, task)
        defer { if current?.operation == operation { current = nil } }
        return try await withTaskCancellationHandler {
            let reply = try await task.value
            try Task.checkCancellation()
            guard current?.operation == operation else { throw IntegrationFailure.cancelled }
            return reply
        } onCancel: { task.cancel() }
    }
    public func cancel(operation: UUID) {
        guard let pending = current, pending.operation == operation else { return }
        current = nil
        // Runtime.submit binds Task cancellation to its private transport ID.
        // Never call the runtime-wide cancel(): another wrapper may own its newer request.
        pending.task.cancel()
    }
}
#endif
