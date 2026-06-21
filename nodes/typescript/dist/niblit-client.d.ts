/**
 * niblit-client.ts — HTTP client for the Niblit Python REST API
 *
 * Provides a typed interface to Niblit's /chat, /state, and /health endpoints.
 * Handles retries, timeout, and error normalization.
 */
import { NiblitStateEnvelope } from "./niblit-state.js";
export interface NiblitClientConfig {
    baseUrl: string;
    apiKey?: string;
    timeoutMs?: number;
    maxRetries?: number;
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
export declare class NiblitClient {
    private readonly baseUrl;
    private readonly apiKey?;
    private readonly timeoutMs;
    private readonly maxRetries;
    constructor(config: NiblitClientConfig);
    chat(message: string, sessionId?: string): Promise<ChatResponse>;
    /** Push the Node.js state envelope to the Python core. */
    pushState(envelope: NiblitStateEnvelope): Promise<boolean>;
    /** Pull the current state envelope from the Python core. */
    pullState(): Promise<NiblitStateEnvelope | null>;
    /**
     * Report this Node environment's capabilities to the Python core.
     * The core merges these into EnvAdapterRegistry / env_state.
     */
    reportEnvCapabilities(caps: Record<string, unknown>): Promise<boolean>;
    health(): Promise<HealthResponse>;
    private _get;
    private _post;
    private _request;
}
//# sourceMappingURL=niblit-client.d.ts.map