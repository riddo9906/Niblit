// JSONValue.swift — Recursive, type-safe JSON value for Swift
//
// Provides a `Codable` enum that can represent any JSON value without
// losing type fidelity.  Used by `NiblitStateEnvelope` for the
// `env_capabilities` and `extras` dictionaries.

import Foundation

/// Type-safe representation of an arbitrary JSON value.
///
/// Mirrors the dynamic dicts used by the Python, TypeScript, and Rust nodes
/// for `env_capabilities` and `extras` without resorting to `[String: Any]`
/// which is not `Codable`.
public indirect enum JSONValue: Codable, Equatable, Sendable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case array([JSONValue])
    case object([String: JSONValue])
    case null

    // MARK: – Codable

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else {
            throw DecodingError.typeMismatch(
                JSONValue.self,
                .init(
                    codingPath: decoder.codingPath,
                    debugDescription: "Unsupported JSON type"
                )
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let v): try container.encode(v)
        case .int(let v):    try container.encode(v)
        case .double(let v): try container.encode(v)
        case .bool(let v):   try container.encode(v)
        case .array(let v):  try container.encode(v)
        case .object(let v): try container.encode(v)
        case .null:          try container.encodeNil()
        }
    }
}

// MARK: – Convenience initialisers

extension JSONValue: ExpressibleByStringLiteral {
    public init(stringLiteral value: String) { self = .string(value) }
}
extension JSONValue: ExpressibleByIntegerLiteral {
    public init(integerLiteral value: Int) { self = .int(value) }
}
extension JSONValue: ExpressibleByFloatLiteral {
    public init(floatLiteral value: Double) { self = .double(value) }
}
extension JSONValue: ExpressibleByBooleanLiteral {
    public init(booleanLiteral value: Bool) { self = .bool(value) }
}
extension JSONValue: ExpressibleByArrayLiteral {
    public init(arrayLiteral elements: JSONValue...) { self = .array(elements) }
}
extension JSONValue: ExpressibleByDictionaryLiteral {
    public init(dictionaryLiteral elements: (String, JSONValue)...) {
        self = .object(Dictionary(uniqueKeysWithValues: elements))
    }
}

// MARK: – String representation

extension JSONValue: CustomStringConvertible {
    public var description: String {
        switch self {
        case .string(let v): return v
        case .int(let v):    return String(v)
        case .double(let v): return String(v)
        case .bool(let v):   return String(v)
        case .null:          return "null"
        case .array(let v):
            return "[\(v.map(\.description).joined(separator: ", "))]"
        case .object(let v):
            let pairs = v.sorted(by: { $0.key < $1.key })
                         .map { "\($0.key): \($0.value)" }
                         .joined(separator: ", ")
            return "{\(pairs)}"
        }
    }
}
