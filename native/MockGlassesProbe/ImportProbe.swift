// Phase 1 link probe: imports the three Meta modules and names one public type
// from each. Nothing here calls into Meta code; main() only prints type names.
// Never run this binary (see README.md).
import MWDATCore
import MWDATCamera
import MWDATMockDevice

let referencedTypes: [Any.Type] = [
    DeviceSession.self,          // MWDATCore
    VideoFrame.self,             // MWDATCamera
    MockDeviceKitConfig.self,    // MWDATMockDevice
]
// Force a real link-time symbol reference without executing SDK logic.
let modelName = GlassesModel.self
print(referencedTypes, modelName)
