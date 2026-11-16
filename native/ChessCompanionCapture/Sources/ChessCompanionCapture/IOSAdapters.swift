#if os(iOS) && canImport(MWDATCore) && canImport(MWDATCamera)
import Foundation
import MWDATCore
import MWDATCamera
import CoreMedia
import UIKit
import AVFoundation

/// Source adapter for the pinned DAT 1.0.1 public interfaces. Importing/constructing this
/// type never configures DAT, registers an account, requests permission or starts a device.
/// An application must supply its explicitly authorized, already-started DeviceSession.
@MainActor public final class DATCaptureAdapter {
    private struct Delivery: Sendable { let frame: VideoFrame; let receivedAt: Double; let mediaPTS: MediaTimestamp? }
    private let coordinator: CaptureCoordinator
    private var camera: Camera?
    private var tokens: [any AnyListenerToken] = []
    private var generation = UUID()
    private var pendingStop: UUID?
    private var captureEpoch: UInt64?
    private var frameTask: Task<Void, Never>?
    private var frameContinuation: AsyncStream<Delivery>.Continuation?

    public init(coordinator: CaptureCoordinator) { self.coordinator = coordinator }

    public func start(in session: DeviceSession) throws {
        guard camera == nil, session.state == .started else { throw CaptureFailure.disconnected }
        let epoch = try coordinator.connect()
        let run = UUID(); generation = run; captureEpoch = epoch; pendingStop = nil
        do {
            guard let camera = try session.addCamera(config: StreamConfiguration(videoCodec: .raw, resolution: .medium, frameRate: 2)) else { throw CaptureFailure.disconnected }
            self.camera = camera
            let (frames, continuation) = AsyncStream<Delivery>.makeStream(bufferingPolicy: .bufferingNewest(1))
            frameContinuation = continuation
            tokens.append(camera.stream.videoFramePublisher.listen { frame in
                // Receipt and media clocks are recorded separately before main-actor scheduling.
                let receivedAt = ProcessInfo.processInfo.systemUptime
                let pts = CMSampleBufferGetPresentationTimeStamp(frame.sampleBuffer)
                let mediaPTS = pts.isValid && pts.isNumeric ? MediaTimestamp(value: pts.value, timescale: pts.timescale) : nil
                // Bounded before any actor hop: one processing frame and one latest buffered frame.
                continuation.yield(Delivery(frame: frame, receivedAt: receivedAt, mediaPTS: mediaPTS))
            })
            frameTask = Task { @MainActor [weak self] in
                for await delivery in frames {
                    guard let self, self.generation == run else { return }
                    guard !Task.isCancelled else { return }
                    self.coordinator.noteIncomingFrame(epoch: epoch)
                    guard let image = delivery.frame.makeUIImage(), let bytes = image.jpegData(compressionQuality: 0.9) else {
                        self.coordinator.captureInterrupted(epoch: epoch); continue
                    }
                    do { try self.coordinator.submitDAT(bytes: bytes, receivedAtHostSeconds: delivery.receivedAt, mediaPTS: delivery.mediaPTS, epoch: epoch) }
                    catch { self.coordinator.captureInterrupted(epoch: epoch) }
                }
            }
            // Revocation here depends on the SDK reporting a stream state change. In Meta's Mock Device Kit 1.0.1
            // (docs/MOCK_GLASSES_RUN.md) taking the glasses off (doff) and denying camera permission mid-stream
            // produced NO state change: frames kept arriving. Fold and power-off did stop the stream. A safety
            // gate must therefore never rely on the stream stopping when the glasses come off.
            tokens.append(camera.stream.statePublisher.listen { [weak self] state in
                Task { @MainActor [weak self] in
                    guard let self, self.generation == run else { return }
                    switch state {
                    case .streaming:
                        self.pendingStop = nil
                        try? self.coordinator.cameraStarted(epoch: epoch)
                    case .stopped:
                        if let stopID = self.pendingStop, self.camera?.stream.state == .stopped {
                            do { try self.coordinator.acknowledgeCameraStopped(epoch: epoch, requestID: stopID) }
                            catch { self.coordinator.captureInterrupted(epoch: epoch) }
                            self.pendingStop = nil
                        } else { self.coordinator.captureInterrupted(epoch: epoch) }
                    case .paused, .waitingForDevice:
                        self.pendingStop = nil; self.coordinator.captureInterrupted(epoch: epoch)
                    case .starting, .stopping: break
                    }
                }
            })
            tokens.append(camera.stream.errorPublisher.listen { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self, self.generation == run else { return }
                    self.pendingStop = nil; self.coordinator.captureInterrupted(epoch: epoch)
                }
            })
            tokens.append(session.statePublisher.listen { [weak self] state in
                Task { @MainActor [weak self] in
                    guard let self, self.generation == run, state != .started else { return }
                    self.pendingStop = nil; self.coordinator.captureInterrupted(epoch: epoch)
                }
            })
            try coordinator.cameraStarted(epoch: epoch)
            camera.stream.start()
        } catch {
            generation = UUID(); coordinator.disconnect(); self.camera?.stop(); self.camera = nil
            frameTask?.cancel(); frameTask = nil; frameContinuation?.finish(); frameContinuation = nil
            let retired = tokens; tokens = []; Task { for token in retired { await token.cancel() } }
            throw error
        }
    }

    /// A stop request alone never enables speech. The matching SDK stopped event is required.
    public func requestStop() throws {
        guard let camera, captureEpoch == coordinator.epoch else { throw CaptureFailure.disconnected }
        pendingStop = try coordinator.requestCameraStop()
        camera.stream.stop()
    }

    public func disconnect() async {
        generation = UUID(); pendingStop = nil; captureEpoch = nil
        coordinator.disconnect(); camera?.stop(); camera = nil
        frameTask?.cancel(); frameTask = nil; frameContinuation?.finish(); frameContinuation = nil
        let retired = tokens; tokens = []
        for token in retired { await token.cancel() }
    }
}

/// Dormant native TTS adapter. No audio session/category/route or permission is changed here.
/// Stopping capture is an experiment guard, not evidence that Gen 1 audio routing works.
@MainActor public final class NativeSpeechOutput: CancellableSpeechOutput {
    private let synthesizer = AVSpeechSynthesizer()
    public init() {}
    public func cancel() { synthesizer.stopSpeaking(at: .immediate) }
    public func speak(_ text: String, permit: SpeechPermit, isCurrent: @escaping @MainActor () -> Bool) async throws {
        guard isCurrent() else { throw CaptureFailure.staleIdentity }
        synthesizer.stopSpeaking(at: .immediate)
        guard isCurrent() else { throw CaptureFailure.staleIdentity }
        synthesizer.speak(AVSpeechUtterance(string: text))
    }
}
#endif
