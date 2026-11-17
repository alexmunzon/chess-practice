import Foundation

/// The occupancy-tracker setting (docs/OCCUPANCY_TRACKER.md "Wiring"). OFF by default.
/// The app keeps no stored settings, so this is a launch argument read once, the first time it is used,
/// and fixed for the life of the process. Only a developer launch tool can pass it; nothing in the app's
/// screens can turn it on. With it off, the bundled runtime refuses every occupancy-tracker request with
/// "Occupancy tracker disabled." and nothing else changes. The app has no picture source, so even with it
/// on nothing in the app sends readings today.
enum TrackerSetting {
    static let launchArgument = "--occupancy-tracker-on"
    static let enabled: Bool = ProcessInfo.processInfo.arguments.contains(launchArgument)
}
