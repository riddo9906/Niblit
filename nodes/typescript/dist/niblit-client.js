"use strict";
/**
 * niblit-client.ts — HTTP client for the Niblit Python REST API
 *
 * Provides a typed interface to Niblit's /chat, /state, and /health endpoints.
 * Handles retries, timeout, and error normalization.
 */
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.NiblitClient = void 0;
const node_fetch_1 = __importDefault(require("node-fetch"));
const niblit_state_js_1 = require("./niblit-state.js");
class NiblitClient {
    constructor(config) {
        this.baseUrl = config.baseUrl.replace(/\/$/, "");
        this.apiKey = config.apiKey;
        this.timeoutMs = config.timeoutMs ?? 15000;
        this.maxRetries = config.maxRetries ?? 3;
    }
    // ── Chat ──────────────────────────────────────────────────────────────────
    async chat(message, sessionId) {
        const body = { message };
        if (sessionId)
            body.session_id = sessionId;
        const json = await this._post("/chat", body);
        return json;
    }
    // ── State exchange ────────────────────────────────────────────────────────
    /** Push the Node.js state envelope to the Python core. */
    async pushState(envelope) {
        const sealed = await (0, niblit_state_js_1.sealEnvelope)(envelope);
        try {
            await this._post("/api/state", sealed);
            return true;
        }
        catch {
            return false;
        }
    }
    /** Pull the current state envelope from the Python core. */
    async pullState() {
        try {
            const data = await this._get("/api/state");
            const valid = await (0, niblit_state_js_1.verifyEnvelope)(data);
            if (!valid) {
                console.warn("[NiblitClient] Received state with invalid checksum — ignoring");
                return null;
            }
            return data;
        }
        catch {
            return null;
        }
    }
    // ── Runtime environment reporting ─────────────────────────────────────────
    /**
     * Report this Node environment's capabilities to the Python core.
     * The core merges these into EnvAdapterRegistry / env_state.
     */
    async reportEnvCapabilities(caps) {
        try {
            await this._post("/api/env/capabilities", {
                runtime: "node",
                platform: `${process.platform}/${process.arch}`,
                node_version: process.version,
                capabilities: caps,
            });
            return true;
        }
        catch {
            return false;
        }
    }
    // ── Health ────────────────────────────────────────────────────────────────
    async health() {
        return this._get("/health");
    }
    // ── Internal ──────────────────────────────────────────────────────────────
    async _get(path) {
        return this._request("GET", path, undefined);
    }
    async _post(path, body) {
        return this._request("POST", path, body);
    }
    async _request(method, path, body, attempt = 1) {
        const url = `${this.baseUrl}${path}`;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), this.timeoutMs);
        const headers = { "Content-Type": "application/json" };
        if (this.apiKey)
            headers["X-Niblit-Key"] = this.apiKey;
        try {
            const res = await (0, node_fetch_1.default)(url, {
                method,
                headers,
                body: body != null ? JSON.stringify(body) : undefined,
                signal: controller.signal,
            });
            if (!res.ok) {
                const text = await res.text().catch(() => "");
                throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
            }
            return (await res.json());
        }
        catch (err) {
            if (attempt < this.maxRetries) {
                const delay = 200 * 2 ** (attempt - 1);
                await new Promise((r) => setTimeout(r, delay));
                return this._request(method, path, body, attempt + 1);
            }
            throw err;
        }
        finally {
            clearTimeout(timer);
        }
    }
}
exports.NiblitClient = NiblitClient;
//# sourceMappingURL=niblit-client.js.map