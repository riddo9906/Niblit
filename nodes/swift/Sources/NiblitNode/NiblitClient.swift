// NiblitClient.swift — URLSession-based async HTTP client for the Niblit REST API
//
// Mirrors the API surface of:
//   nodes/typescript/src/niblit-client.ts
//   nodes/rust/src/niblit_client.rs
//
// Endpoints used:
//   GET  /health               — health check + runtime level
//   POST /chat                 — send a message; receive a response
//   GET  /api/state            — pull NiblitStateEnvelope
//   POST /api/state            — push NiblitStateEnvelope
//   POST /api/env/capabilities — report Swift environment capabilities

import Foundation

// MARK: – Response types

public struct ChatResponse: Decodable, Sendable {
    public let response: String
    public let sessionId: String?

    enum CodingKeys: String, CodingKey {
        case response
        case sessionId = "session_id"
    }
}

public struct HealthResponse: Decodable, Sendable {
    public let status: String
    public let version: String?
    public let runtimeLevel: Double?

    enum CodingKeys: String, CodingKey {
        case status
        case version
        case runtimeLevel = "runtime_level"
    }
}

// MARK: – Client

/// Async HTTP client for the Niblit Python core REST API.
public final class NiblitClient: Sendable {

    private let baseURL: URL
    private let apiKey: String?
    private let session: URLSession

    // MARK: – Init

    public init(baseURL: String, apiKey: String? = nil, timeoutSeconds: Double = 20) {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest  = timeoutSeconds
        config.timeoutIntervalForResource = timeoutSeconds * 3

        self.baseURL = URL(string: baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")))!
        self.apiKey  = apiKey
        self.session = URLSession(configuration: config)
    }

    // MARK: – Health

    public func health() async throws -> HealthResponse {
        let req = makeRequest(path: "/health", method: "GET")
        return try await decode(HealthResponse.self, from: req)
    }

    // MARK: – Chat

    public func chat(message: String, sessionId: String? = nil) async throws -> ChatResponse {
        var body: [String: String] = ["message": message]
        if let sid = sessionId { body["session_id"] = sid }
        let req = try makeJSONRequest(path: "/chat", method: "POST", body: body)
        return try await decode(ChatResponse.self, from: req)
    }

    // MARK: – State exchange

    public func pushState(_ envelope: NiblitStateEnvelope) async throws -> Bool {
        let req = try makeJSONRequest(path: "/api/state", method: "POST", body: envelope)
        let (_, response) = try await session.data(for: req)
        return (response as? HTTPURLResponse)?.statusCode ?? 0 < 400
    }

    public func pullState() async throws -> NiblitStateEnvelope? {
        let req = makeRequest(path: "/api/state", method: "GET")
        let (data, response) = try await session.data(for: req)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        let envelope = try JSONDecoder.niblit.decode(NiblitStateEnvelope.self, from: data)
        guard envelope.verify() else {
            fputs("[NiblitClient] Received state with invalid checksum — ignoring\n", stderr)
            return nil
        }
        return envelope
    }

    // MARK: – Environment capabilities

    @discardableResult
    public func reportEnvCapabilities(_ caps: [String: JSONValue]) async throws -> Bool {
        let req = try makeJSONRequest(
            path: "/api/env/capabilities",
            method: "POST",
            body: caps
        )
        let (_, response) = try await session.data(for: req)
        return (response as? HTTPURLResponse)?.statusCode ?? 0 < 400
    }

    // MARK: – Request helpers

    private func url(for path: String) -> URL {
        baseURL.appendingPathComponent(path)
    }

    private func makeRequest(path: String, method: String) -> URLRequest {
        var req = URLRequest(url: url(for: path))
        req.httpMethod = method
        if let key = apiKey {
            req.setValue(key, forHTTPHeaderField: "X-Niblit-Key")
        }
        return req
    }

    private func makeJSONRequest<Body: Encodable>(
        path: String,
        method: String,
        body: Body
    ) throws -> URLRequest {
        var req = makeRequest(path: path, method: method)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder.niblit.encode(body)
        return req
    }

    private func decode<T: Decodable>(_ type: T.Type, from request: URLRequest) async throws -> T {
        let (data, _) = try await session.data(for: request)
        return try JSONDecoder.niblit.decode(type, from: data)
    }
}

// MARK: – Shared encoder / decoder

extension JSONEncoder {
    /// Canonical encoder: sorted keys so checksums are stable.
    public static let niblit: JSONEncoder = {
        let enc = JSONEncoder()
        enc.outputFormatting = .sortedKeys
        return enc
    }()
}

extension JSONDecoder {
    public static let niblit = JSONDecoder()
}
