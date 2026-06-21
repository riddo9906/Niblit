/**
 * niblit-client.ts — HTTP client for the Niblit Python REST API
 *
 * Provides a typed interface to Niblit's /chat, /state, and /health endpoints.
 * Handles retries, timeout, and error normalization.
 */

import fetch from "node-fetch";
import { NiblitStateEnvelope, sealEnvelope, verifyEnvelope } from "./niblit-state.js";

export interface NiblitClientConfig {
  baseUrl: string;         // e.g. "http://localhost:8000" or your Fly.io URL
  apiKey?: string;         // Optional NIBLIT_API_KEY header
  timeoutMs?: number;      // Default 15 000
  maxRetries?: number;     // Default 3
}

export interface ChatResponse {
  response: string;
  session_id?: string;
}

export interface HealthResponse {
  status: string;
  version?: string;
  runtime_level?: number;
}

export class NiblitClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;

  constructor(config: NiblitClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, "");
    this.apiKey = config.apiKey;
    this.timeoutMs = config.timeoutMs ?? 15_000;
    this.maxRetries = config.maxRetries ?? 3;
  }

  // ── Chat ──────────────────────────────────────────────────────────────────

  async chat(message: string, sessionId?: string): Promise<ChatResponse> {
    const body: Record<string, string> = { message };
    if (sessionId) body.session_id = sessionId;
    const json = await this._post<ChatResponse>("/chat", body);
    return json;
  }

  // ── State exchange ────────────────────────────────────────────────────────

  /** Push the Node.js state envelope to the Python core. */
  async pushState(envelope: NiblitStateEnvelope): Promise<boolean> {
    const sealed = await sealEnvelope(envelope);
    try {
      await this._post("/api/state", sealed);
      return true;
    } catch {
      return false;
    }
  }

  /** Pull the current state envelope from the Python core. */
  async pullState(): Promise<NiblitStateEnvelope | null> {
    try {
      const data = await this._get<NiblitStateEnvelope>("/api/state");
      const valid = await verifyEnvelope(data);
      if (!valid) {
        console.warn("[NiblitClient] Received state with invalid checksum — ignoring");
        return null;
      }
      return data;
    } catch {
      return null;
    }
  }

  // ── Runtime environment reporting ─────────────────────────────────────────

  /**
   * Report this Node environment's capabilities to the Python core.
   * The core merges these into EnvAdapterRegistry / env_state.
   */
  async reportEnvCapabilities(caps: Record<string, unknown>): Promise<boolean> {
    try {
      await this._post("/api/env/capabilities", {
        runtime: "node",
        platform: `${process.platform}/${process.arch}`,
        node_version: process.version,
        capabilities: caps,
      });
      return true;
    } catch {
      return false;
    }
  }

  // ── Health ────────────────────────────────────────────────────────────────

  async health(): Promise<HealthResponse> {
    return this._get<HealthResponse>("/health");
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  private async _get<T>(path: string): Promise<T> {
    return this._request<T>("GET", path, undefined);
  }

  private async _post<T>(path: string, body: unknown): Promise<T> {
    return this._request<T>("POST", path, body);
  }

  private async _request<T>(
    method: string,
    path: string,
    body: unknown,
    attempt = 1,
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.apiKey) headers["X-Niblit-Key"] = this.apiKey;

   try {
  const res = await fetch(url, {
    method,
    headers,
    body: body != null ? JSON.stringify(body) : undefined,
    signal: controller.signal,
  });

      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
      }

      return (await res.json()) as T;
    } catch (err) {
      if (attempt < this.maxRetries) {
        const delay = 200 * 2 ** (attempt - 1);
        await new Promise((r) => setTimeout(r, delay));
        return this._request<T>(method, path, body, attempt + 1);
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }
}
