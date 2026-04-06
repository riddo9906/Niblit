// NiblitStateTests.swift — Unit tests for NiblitStateEnvelope
//
// Tests verify:
//   • A fresh envelope can be created and sealed.
//   • Verify passes immediately after seal.
//   • Mutating any field invalidates the checksum.
//   • JSON round-trip preserves all fields including the checksum.
//   • snake_case ↔ camelCase CodingKeys are correct.

import XCTest
import NiblitNode

final class NiblitStateTests: XCTestCase {

    // MARK: – Seal and verify

    func testSealAndVerify() {
        var env = NiblitStateEnvelope.new()
        XCTAssertFalse(env.verify(), "Unsealed envelope should fail verification")
        env.seal()
        XCTAssertTrue(env.verify(), "Sealed envelope should pass verification")
    }

    func testSealedCopyVerifies() {
        let env = NiblitStateEnvelope.new().sealed()
        XCTAssertTrue(env.verify(), "sealed() copy should pass verification")
    }

    func testMutationInvalidatesChecksum() {
        var env = NiblitStateEnvelope.new()
        env.seal()
        env.totalCommands += 1   // mutate without re-sealing
        XCTAssertFalse(env.verify(), "Mutated envelope must fail verification")
    }

    func testResealAfterMutation() {
        var env = NiblitStateEnvelope.new()
        env.seal()
        env.totalCommands += 1
        env.seal()
        XCTAssertTrue(env.verify(), "Re-sealed envelope must pass verification")
    }

    // MARK: – Checksum stability

    func testChecksumIsDeterministic() {
        let env = NiblitStateEnvelope.new().sealed()
        let c1  = env.computeChecksum()
        let c2  = env.computeChecksum()
        XCTAssertEqual(c1, c2, "computeChecksum() must be deterministic")
    }

    func testChecksumLengthIs16() {
        let cs = NiblitStateEnvelope.new().computeChecksum()
        XCTAssertEqual(cs.count, 16, "Checksum must be exactly 16 hex characters")
    }

    // MARK: – JSON round-trip

    func testJSONRoundTrip() throws {
        let original = NiblitStateEnvelope.new().sealed()
        let data     = try JSONEncoder.niblit.encode(original)
        let decoded  = try JSONDecoder.niblit.decode(NiblitStateEnvelope.self, from: data)

        XCTAssertEqual(original.sessionId,           decoded.sessionId)
        XCTAssertEqual(original.niblitVersion,       decoded.niblitVersion)
        XCTAssertEqual(original.originRuntime,       decoded.originRuntime)
        XCTAssertEqual(original.lastRuntime,         decoded.lastRuntime)
        XCTAssertEqual(original.totalCommands,       decoded.totalCommands)
        XCTAssertEqual(original.checksum,            decoded.checksum)
        XCTAssertTrue(decoded.verify(), "Decoded envelope must still verify")
    }

    // MARK: – snake_case field names

    func testSnakeCaseFieldNames() throws {
        let env  = NiblitStateEnvelope.new().sealed()
        let data = try JSONEncoder.niblit.encode(env)
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            XCTFail("Expected JSON object"); return
        }

        // Verify a selection of snake_case keys are present
        let expectedKeys = [
            "session_id", "niblit_version", "origin_runtime", "origin_platform",
            "last_runtime", "runtime_history", "total_commands", "total_facts",
            "total_interactions", "known_topics", "knowledge_summary",
            "last_command", "last_response_snippet", "last_active_ts",
            "env_capabilities", "extras", "checksum",
        ]
        for key in expectedKeys {
            XCTAssertNotNil(json[key], "Expected key '\(key)' in JSON")
        }
    }

    // MARK: – Origin runtime

    func testOriginRuntimeIsSwift() {
        let env = NiblitStateEnvelope.new()
        XCTAssertEqual(env.originRuntime, "swift")
        XCTAssertEqual(env.lastRuntime,   "swift")
    }

    // MARK: – JSONValue

    func testJSONValueRoundTrip() throws {
        let value: JSONValue = .object([
            "name":  .string("niblit"),
            "level": .double(1.0),
            "active": .bool(true),
            "tags":   .array([.string("ai"), .string("swift")]),
        ])

        let encoded = try JSONEncoder().encode(value)
        let decoded = try JSONDecoder().decode(JSONValue.self, from: encoded)
        XCTAssertEqual(value, decoded)
    }
}
