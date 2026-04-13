// swift-tools-version: 5.9
// Package.swift — Niblit Swift deployment node
//
// This package provides a Swift executable that:
//   • Connects to the Niblit Python core REST API
//   • Exchanges NiblitStateEnvelope across Python / Node.js / Rust / Swift runtimes
//   • Registers with the Niblit self-improving runtime and responds to challenges
//   • Provides an interactive CLI + single-command mode
//
// Dependencies are intentionally minimal (only swift-argument-parser);
// networking uses Foundation's URLSession and hashing uses CryptoKit — both
// platform-native frameworks that require no additional packages.
//
// Targets:
//   NiblitNode      — library target with all core logic (importable by tests)
//   NiblitNodeExec  — thin executable wrapper that calls NiblitNodeCommand.main()
//
// Build:
//   swift build                   # debug
//   swift build -c release        # optimised binary
//   swift test                    # run unit tests
//
// Run:
//   NIBLIT_URL=http://localhost:8000 .build/release/niblit-node
//   NIBLIT_URL=http://localhost:8000 .build/release/niblit-node "tell me about AI"

import PackageDescription

let package = Package(
    name: "NiblitNode",
    platforms: [
        .macOS(.v13),  // CryptoKit SHA-256 and async/await require macOS 12+; 13 for stability
    ],
    products: [
        .executable(name: "niblit-node", targets: ["NiblitNodeExec"]),
        .library(name: "NiblitNodeCore", targets: ["NiblitNode"]),
    ],
    dependencies: [
        // CLI argument parsing — mirroring the Rust node's use of clap
        .package(
            url: "https://github.com/apple/swift-argument-parser",
            from: "1.3.0"
        ),
        // Cross-platform SHA-256 (CryptoKit on Apple, swift-crypto on Linux)
        .package(
            url: "https://github.com/apple/swift-crypto",
            from: "4.3.1"
        ),
    ],
    targets: [
        // Library target — all core logic (testable)
        .target(
            name: "NiblitNode",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                .product(name: "Crypto", package: "swift-crypto", condition: .when(platforms: [.linux, .windows])),
            ],
            path: "Sources/NiblitNode"
        ),
        // Thin executable wrapper
        .executableTarget(
            name: "NiblitNodeExec",
            dependencies: ["NiblitNode"],
            path: "Sources/NiblitNodeExec"
        ),
        // Test target
        .testTarget(
            name: "NiblitNodeTests",
            dependencies: ["NiblitNode"],
            path: "Tests/NiblitNodeTests"
        ),
    ]
)
