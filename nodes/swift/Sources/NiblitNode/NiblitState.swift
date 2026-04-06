// NiblitState.swift — Portable state envelope for the Swift deployment node
//
// Mirrors the Python NiblitStateEnvelope (modules/env_state.py),
// the TypeScript version (nodes/typescript/src/niblit-state.ts), and
// the Rust version (nodes/rust/src/niblit_state.rs) exactly.
//
// The checksum algorithm is:
//   1. Encode the envelope to JSON (sorted keys, without the checksum field).
//   2. SHA-256 hash the UTF-8 bytes.
//   3. Hex-encode the digest and take the first 16 characters.
//
// All four runtimes (Python / Node / Rust / Swift) use this same algorithm,
// so envelopes can be safely transferred between them over the REST API.

import CryptoKit
import Foundation

// MARK: – Envelope

/// Cross-runtime portable state envelope.
///
/// JSON field names use snake_case to match the Python/Rust/TypeScript schema.
public struct NiblitStateEnvelope: Codable, Sendable {

    // ── Identity ─────────────────────────────────────────────────────────────
    public var sessionId: String
    public var niblitVersion: String

    // ── Runtime provenance ───────────────────────────────────────────────────
    public var originRuntime: String
    public var originPlatform: String
    public var lastRuntime: String
    public var runtimeHistory: [String]

    // ── Session counters ─────────────────────────────────────────────────────
    public var totalCommands: Int
    public var totalFacts: Int
    public var totalInteractions: Int

    // ── Knowledge snapshot ───────────────────────────────────────────────────
    public var knownTopics: [String]
    public var knowledgeSummary: String

    // ── Last active state ─────────────────────────────────────────────────────
    public var lastCommand: String
    public var lastResponseSnippet: String
    public var lastActiveTs: Double

    // ── Environment capabilities ─────────────────────────────────────────────
    public var envCapabilities: [String: JSONValue]

    // ── Runtime-specific extras ───────────────────────────────────────────────
    public var extras: [String: JSONValue]

    // ── Integrity ─────────────────────────────────────────────────────────────
    public var checksum: String

    // MARK: – CodingKeys (snake_case ↔ camelCase)

    enum CodingKeys: String, CodingKey {
        case sessionId            = "session_id"
        case niblitVersion        = "niblit_version"
        case originRuntime        = "origin_runtime"
        case originPlatform       = "origin_platform"
        case lastRuntime          = "last_runtime"
        case runtimeHistory       = "runtime_history"
        case totalCommands        = "total_commands"
        case totalFacts           = "total_facts"
        case totalInteractions    = "total_interactions"
        case knownTopics          = "known_topics"
        case knowledgeSummary     = "knowledge_summary"
        case lastCommand          = "last_command"
        case lastResponseSnippet  = "last_response_snippet"
        case lastActiveTs         = "last_active_ts"
        case envCapabilities      = "env_capabilities"
        case extras
        case checksum
    }
}

// MARK: – Factory

extension NiblitStateEnvelope {

    /// Create a fresh envelope for the Swift runtime.
    public static func new() -> Self {
        let now = Date().timeIntervalSince1970
        let platform = "\(operatingSystemName())/\(cpuArchitecture())"

        return NiblitStateEnvelope(
            sessionId:           UUID().uuidString,
            niblitVersion:       "1.0",
            originRuntime:       "swift",
            originPlatform:      platform,
            lastRuntime:         "swift",
            runtimeHistory:      [],
            totalCommands:       0,
            totalFacts:          0,
            totalInteractions:   0,
            knownTopics:         [],
            knowledgeSummary:    "",
            lastCommand:         "",
            lastResponseSnippet: "",
            lastActiveTs:        now,
            envCapabilities:     [:],
            extras:              [:],
            checksum:            ""
        )
    }
}

// MARK: – Checksum

extension NiblitStateEnvelope {

    /// Compute the 16-character SHA-256 prefix checksum used by all Niblit runtimes.
    ///
    /// Algorithm:
    ///   1. Encode the envelope to a JSON object.
    ///   2. Remove the `checksum` key.
    ///   3. Re-serialise with sorted keys.
    ///   4. SHA-256 hash; return first 16 hex characters.
    public func computeChecksum() -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys

        // Encode → Dictionary → remove checksum → re-encode
        guard
            let data     = try? encoder.encode(self),
            var dict     = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return "" }

        dict.removeValue(forKey: "checksum")

        guard
            let stable   = try? JSONSerialization.data(
                withJSONObject: dict,
                options: [.sortedKeys]   // Foundation sort_keys=True equivalent
            )
        else { return "" }

        let digest = SHA256.hash(data: stable)
        let hex    = digest.map { String(format: "%02x", $0) }.joined()
        return String(hex.prefix(16))
    }

    /// Return a copy with the checksum field filled in.
    public func sealed() -> Self {
        var copy = self
        copy.checksum = copy.computeChecksum()
        return copy
    }

    /// Mutate in place: compute and store the checksum.
    public mutating func seal() {
        checksum = computeChecksum()
    }

    /// Verify the stored checksum matches the envelope contents.
    public func verify() -> Bool {
        checksum == computeChecksum()
    }
}

// MARK: – Platform helpers

private func operatingSystemName() -> String {
#if os(macOS)
    return "macOS"
#elseif os(Linux)
    return "Linux"
#else
    return "unknown"
#endif
}

private func cpuArchitecture() -> String {
#if arch(arm64)
    return "arm64"
#elseif arch(x86_64)
    return "x86_64"
#else
    return "unknown"
#endif
}
