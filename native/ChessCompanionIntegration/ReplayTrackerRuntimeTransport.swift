import Foundation
#if canImport(ChessCompanionRuntime)
import ChessCompanionRuntime
#endif

/// Adapts the phone-local JSON transport (normally `NativeRuntimeTransport` around
/// `NativeEngineRuntime`) to `ReplayTrackerTransport`. Tracker requests travel through the
/// same single-pending runtime as engine commands: sending one cancels any in-flight
/// engine analysis, whose caller then sees a cancellation error. Every submission gets
/// a fresh operation UUID, so cancelling this task never cancels a newer request.
/// Dormant: constructing it starts no WebKit, capture, analysis or speech.
@MainActor public final class ReplayTrackerRuntimeTransport: ReplayTrackerTransport {
    private let transport: any LocalJSONTransport
    public init(transport: any LocalJSONTransport) { self.transport = transport }
    #if COMPANION_RUNTIME_SOURCE || canImport(ChessCompanionRuntime)
    public convenience init(runtime: NativeEngineRuntime) { self.init(transport: NativeRuntimeTransport(runtime: runtime)) }
    #endif
    public func submit(requestJSON: String, timeoutMilliseconds: Int) async throws -> String {
        try Task.checkCancellation()
        let operation = UUID(), transport = self.transport
        return try await withTaskCancellationHandler {
            try await transport.submit(commandJSON: requestJSON, operation: operation, timeoutMilliseconds: timeoutMilliseconds)
        } onCancel: { Task { @MainActor [weak self] in self?.transport.cancel(operation: operation) } }
    }
}
