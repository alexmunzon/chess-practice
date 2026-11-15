import SwiftUI

// Placeholder app. Its only job is to give Xcode a signable target so that
// `xcodebuild -allowProvisioningUpdates` creates the development certificate
// and provisioning profile for this bundle ID and the connected phone.
@main
struct ProvisioningShellApp: App {
    var body: some Scene {
        WindowGroup { Text("Provisioning shell") }
    }
}
