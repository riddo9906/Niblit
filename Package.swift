// swift-tools-version: 5.9
// Package.swift — Root-level Swift package manifest for Niblit
//
// This manifest aggregates all Swift targets in the repository so that
// `swift build` at the repo root succeeds.  CodeQL autobuild and any CI
// that runs `swift build` from the working directory will discover this
// file automatically.
//
// Targets:
//   NiblitNode      — library: deployment-node core logic  (nodes/swift/)
//   NiblitNodeExec  — executable: CLI wrapper              (nodes/swift/)
//   AleSwiftModule  — executable: ALE-generated module     (builds/swift/)
//   NiblitNodeTests — tests                                (nodes/swift/)

import PackageDescription

let package = Package(
    name: "Niblit",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .executable(name: "niblit-node", targets: ["NiblitNodeExec"]),
        .library(name: "NiblitNodeCore", targets: ["NiblitNode"]),
        .executable(name: "ale-swift-module", targets: ["AleSwiftModule"]),
    ],
    dependencies: [
        .package(
            url: "https://github.com/apple/swift-crypto",
            from: "4.3.1"
        ),
    ],
    targets: [
        // ── Deployment node (library) ────────────────────────────────────
        .target(
            name: "NiblitNode",
            dependencies: [
                .product(name: "Crypto", package: "swift-crypto", condition: .when(platforms: [.linux, .windows])),
            ],
            path: "nodes/swift/Sources/NiblitNode"
        ),

        // ── Deployment node (executable wrapper) ─────────────────────────
        .executableTarget(
            name: "NiblitNodeExec",
            dependencies: ["NiblitNode"],
            path: "nodes/swift/Sources/NiblitNodeExec"
        ),

        // ── ALE-generated Swift module ───────────────────────────────────
        .executableTarget(
            name: "AleSwiftModule",
            path: "builds/swift"
        ),

        // ── Tests ────────────────────────────────────────────────────────
        .testTarget(
            name: "NiblitNodeTests",
            dependencies: ["NiblitNode"],
            path: "nodes/swift/Tests/NiblitNodeTests"
        ),
    ]
)
