/**
 * niblit-state.ts — Niblit portable state envelope for TypeScript
 *
 * Mirrors the Python NiblitStateEnvelope schema exactly.
 * Any TypeScript component that exchanges state with the Niblit Python core
 * must use this interface.
 */

export interface NiblitStateEnvelope {
  // Identity
  session_id: string;
  niblit_version: string;

  // Runtime provenance
  origin_runtime: "python" | "node" | "rust" | "browser" | "other";
  origin_platform: string;
  last_runtime: string;
  runtime_history: string[];

  // Session counters
  total_commands: number;
  total_facts: number;
  total_interactions: number;

  // Knowledge snapshot
  known_topics: string[];
  knowledge_summary: string;

  // Last active state
  last_command: string;
  last_response_snippet: string;
  last_active_ts: number;

  // Environment capabilities
  env_capabilities: Record<string, unknown>;

  // Runtime-specific extras
  extras: Record<string, unknown>;

  // Integrity
  checksum: string;
}

/**
 * Compute the same 16-char SHA-256 prefix checksum as the Python side.
 * Uses the Web Crypto API (Node 19+) or the node:crypto module.
 */
export async function computeChecksum(envelope: NiblitStateEnvelope): Promise<string> {
  const { createHash } = await import("node:crypto");
  const stable = { ...envelope };
  delete (stable as Partial<NiblitStateEnvelope>).checksum;
  const raw = JSON.stringify(stable, Object.keys(stable).sort());
  return createHash("sha256").update(raw).digest("hex").slice(0, 16);
}

export async function sealEnvelope(envelope: NiblitStateEnvelope): Promise<NiblitStateEnvelope> {
  const sealed = { ...envelope };
  sealed.checksum = await computeChecksum(envelope);
  return sealed;
}

export async function verifyEnvelope(envelope: NiblitStateEnvelope): Promise<boolean> {
  const expected = await computeChecksum(envelope);
  return expected === envelope.checksum;
}

export function emptyEnvelope(sessionId?: string): NiblitStateEnvelope {
  const { randomUUID } = require("node:crypto");
  return {
    session_id: sessionId ?? randomUUID(),
    niblit_version: "1.0",
    origin_runtime: "node",
    origin_platform: `${process.platform}/${process.arch}`,
    last_runtime: "node",
    runtime_history: [],
    total_commands: 0,
    total_facts: 0,
    total_interactions: 0,
    known_topics: [],
    knowledge_summary: "",
    last_command: "",
    last_response_snippet: "",
    last_active_ts: Date.now() / 1000,
    env_capabilities: {},
    extras: {},
    checksum: "",
  };
}
