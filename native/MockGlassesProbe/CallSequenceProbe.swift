// Phase 1 API probe: type-checks and links the exact call sequence Phase 3 needs.
// mockCaptureSequence() is NEVER called; this file only proves the signatures.
// It uses only the file-based camera feed; the phone-camera feed is never referenced.
// Never run this binary (see README.md).
import CoreMedia
import Foundation
import MWDATCore
import MWDATCamera
import MWDATMockDevice

struct FrameStamp: Sendable {
    let pts: CMTime            // presentation timestamp from the CMSampleBuffer
    let duration: CMTime
    let width: Int32
    let height: Int32
    let pixelFormat: FourCharCode
}

func stamp(_ frame: VideoFrame) -> FrameStamp {
    let buffer = frame.sampleBuffer
    let format = CMSampleBufferGetFormatDescription(buffer)
    let dims = format.map { CMVideoFormatDescriptionGetDimensions($0) }
    return FrameStamp(
        pts: CMSampleBufferGetPresentationTimeStamp(buffer),
        duration: CMSampleBufferGetDuration(buffer),
        width: dims?.width ?? 0,
        height: dims?.height ?? 0,
        pixelFormat: format.map { CMFormatDescriptionGetMediaSubType($0) } ?? 0)
}

/// Phase 3 sequence. Returns the objects that must be kept alive.
func mockCaptureSequence(videoFile: URL,
                         onFrame: @escaping @Sendable (FrameStamp) -> Void) throws
    -> (DeviceSession, Camera, any AnyListenerToken) {
    // 1. Configure the SDK (throws WearablesError).
    try Wearables.configure()
    // 2. Enable the mock kit: registration and permissions start granted.
    let kit = MockDeviceKit.shared
    kit.enable(config: MockDeviceKitConfig(initiallyRegistered: true, initialPermissionsGranted: true))
    // 3. Pair a Ray-Ban Meta mock (typed throws: MockDeviceKitError).
    let glasses: any MockGlasses = try kit.pairGlasses(model: .rayBanMeta)
    // 4. Power on and don (wear) it; both are synchronous, non-throwing.
    glasses.powerOn()
    glasses.unfold()
    glasses.don()
    // 5. File-based camera feed (H.265 video).
    glasses.services.camera.setCameraFeed(fileURL: videoFile)
    // 6. Session on that specific mock device (typed throws: DeviceSessionError).
    let session = try Wearables.shared.createSession(
        deviceSelector: SpecificDeviceSelector(device: glasses.deviceIdentifier))
    try session.start()
    // 7. Camera capability + stream (addCamera is an extension from MWDATCamera).
    let config = StreamConfiguration(videoCodec: .raw, resolution: .high, frameRate: 30)
    guard let camera = try session.addCamera(config: config) else { throw ProbeError.noCamera }
    // 8. Frames arrive through an Announcer listener (not an AsyncSequence).
    let token = camera.stream.videoFramePublisher.listen { (frame: VideoFrame) in
        onFrame(stamp(frame))
    }
    camera.stream.start()
    return (session, camera, token)
}

enum ProbeError: Error { case noCamera }

// Top-level code: does not call any SDK function.
print("CallSequenceProbe: compile-only artifact; not meant to be executed.",
      String(describing: mockCaptureSequence as Any))
