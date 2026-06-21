/**
 * niblit-state.ts — Niblit portable state envelope for TypeScript
 *
 * Mirrors the Python NiblitStateEnvelope schema exactly.
 * Any TypeScript component that exchanges state with the Niblit Python core
 * must use this interface.
 */
export interface NiblitStateEnvelope {
    session_id: string;
    niblit_version: string;
    origin_runtime: "python" | "node" | "rust" | "browser" | "other";
    origin_platform: string;
    last_runtime: string;
    runtime_history: string[];
    total_commands: number;
    total_facts: number;
    total_interactions: number;
    known_topics: string[];
    knowledge_summary: string;
    last_command: string;
    last_response_snippet: string;
    last_active_ts: number;
    env_capabilities: Record<string, unknown>;
    extras: Record<string, unknown>;
    checksum: string;
}
/**
 * Compute the same 16-char SHA-256 prefix checksum as the Python side.
 * Uses the Web Crypto API (Node 19+) or the node:crypto module.
 */
export declare function computeChecksum(envelope: NiblitStateEnvelope): Promise<string>;
export declare function sealEnvelope(envelope: NiblitStateEnvelope): Promise<NiblitStateEnvelope>;
export declare function verifyEnvelope(envelope: NiblitStateEnvelope): Promise<boolean>;
export declare function emptyEnvelope(sessionId?: string): NiblitStateEnvelope;
//# sourceMappingURL=niblit-state.d.ts.map