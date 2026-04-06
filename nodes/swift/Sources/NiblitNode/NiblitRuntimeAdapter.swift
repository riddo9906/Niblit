// NiblitRuntimeAdapter.swift — Niblit self-improving runtime adapter for Swift
//
// Implements the same contract as:
//   nodes/typescript/src/niblit-runtime-adapter.ts
//   nodes/rust/src/main.rs  (inline capability reporting)
//
// The Niblit Python core (modules/niblit_runtime.py) raises its NiblitRuntime
// level over time and issues AdaptationChallenges to registered components.
// This adapter automatically:
//   • Adopts every capability listed in the challenge.
//   • Bumps its declared level to match the runtime.
//   • Reports the new state back via /api/env/capabilities.

import Foundation

// MARK: – Protocol

/// Contract every Niblit runtime adapter must satisfy.
public protocol NiblitRuntimeAdapterProtocol: AnyObject, Sendable {
    /// Current declared compatibility level of this node.
    var level: Double { get }
    /// Capabilities this node has adopted.
    var capabilities: Set<String> { get }
    /// Called when the Python core issues an adaptation challenge.
    func onChallenge(_ challenge: AdaptationChallenge) async
    /// Push the current level/capabilities back to the Python core.
    @discardableResult func reportLevel() async -> Bool
}

// MARK: – AdaptationChallenge

/// Issued by the Python NiblitRuntime when it raises its level.
public struct AdaptationChallenge: Decodable, Sendable {
    public let componentName:        String
    public let currentRuntimeLevel:  Double
    public let componentLevel:       Double
    public let delta:                Double
    public let requiredCapabilities: [String]
    public let guidance:             [String: String]
    public let issuedAt:             Double
    public let deadlineSecs:         Double

    enum CodingKeys: String, CodingKey {
        case componentName        = "component_name"
        case currentRuntimeLevel  = "current_runtime_level"
        case componentLevel       = "component_level"
        case delta
        case requiredCapabilities = "required_capabilities"
        case guidance
        case issuedAt             = "issued_at"
        case deadlineSecs         = "deadline_secs"
    }
}

// MARK: – Default adapter

/// Automatically adopts all capabilities listed in each challenge and bumps
/// its declared level to keep in sync with the Niblit runtime.
public final class DefaultSwiftRuntimeAdapter: NiblitRuntimeAdapterProtocol {

    public private(set) var level: Double
    public private(set) var capabilities: Set<String>

    private let client: NiblitClient
    private let name:   String

    public init(
        client:       NiblitClient,
        initialLevel: Double = 1.0,
        name:         String = "niblit-swift-node"
    ) {
        self.client       = client
        self.level        = initialLevel
        self.name         = name
        self.capabilities = ["state_portability", "knowledge_exchange", "swift_native"]
    }

    // MARK: – Challenge handling

    public func onChallenge(_ challenge: AdaptationChallenge) async {
        fputs(
            "[NiblitRuntimeAdapter] Challenge: runtime=\(String(format: "%.4f", challenge.currentRuntimeLevel))" +
            " our_level=\(String(format: "%.4f", challenge.componentLevel))" +
            " delta=\(String(format: "%.4f", challenge.delta))\n",
            stderr
        )

        // Adopt every required capability
        for cap in challenge.requiredCapabilities {
            capabilities.insert(cap)
            fputs("[NiblitRuntimeAdapter] Adopted capability: \(cap)\n", stderr)
        }

        // Advance level to match the runtime
        level = challenge.currentRuntimeLevel
        fputs("[NiblitRuntimeAdapter] Self-adapted to level \(String(format: "%.4f", level))\n", stderr)

        await reportLevel()
    }

    // MARK: – Level reporting

    @discardableResult
    public func reportLevel() async -> Bool {
        let caps: [String: JSONValue] = [
            "component_name":  .string(name),
            "declared_level":  .double(level),
            "capabilities":    .array(capabilities.sorted().map { .string($0) }),
            "runtime":         .string("swift"),
            "platform":        .string(currentPlatform()),
            "swift_version":   .string(swiftVersion()),
        ]
        do {
            return try await client.reportEnvCapabilities(caps)
        } catch {
            fputs("[NiblitRuntimeAdapter] reportLevel failed: \(error)\n", stderr)
            return false
        }
    }
}

// MARK: – Platform helpers

private func currentPlatform() -> String {
#if os(macOS)
    let os = "macOS"
#elseif os(Linux)
    let os = "Linux"
#else
    let os = "unknown"
#endif

#if arch(arm64)
    let arch = "arm64"
#elseif arch(x86_64)
    let arch = "x86_64"
#else
    let arch = "unknown"
#endif

    return "\(os)/\(arch)"
}

private func swiftVersion() -> String {
#if swift(>=5.10)
    return "5.10+"
#elseif swift(>=5.9)
    return "5.9"
#else
    return "5.x"
#endif
}
