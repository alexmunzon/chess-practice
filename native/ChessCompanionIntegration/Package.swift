// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ChessCompanionIntegration",
    platforms: [.macOS(.v14), .iOS("17.2")],
    products: [.library(name: "ChessCompanionIntegration", targets: ["ChessCompanionIntegration"])],
    dependencies: [.package(path: "../ChessCompanionCapture"), .package(path: "../ChessCompanionVision"), .package(path: "../ChessCompanionRuntime")],
    targets: [.target(name: "ChessCompanionIntegration", dependencies: ["ChessCompanionCapture", "ChessCompanionVision", "ChessCompanionRuntime"],
                      path: ".", exclude: ["README.md", "IntegrationChecks.swift"], sources: ["Adapters.swift", "RuntimeTransport.swift"])]
)
