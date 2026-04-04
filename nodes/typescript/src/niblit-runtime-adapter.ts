/**
 * niblit-runtime-adapter.ts — Niblit Runtime compatibility adapter for Node.js
 *
 * Implements the Niblit runtime adaptation contract:
 * - Registers this Node.js component with the Python NiblitRuntime
 * - Accepts AdaptationChallenges and self-adapts by adopting new capabilities
 * - Reports its current level back so the runtime knows it's keeping up
 */

import { NiblitClient } from "./niblit-client.js";

export interface AdaptationChallenge {
  component_name: string;
  current_runtime_level: number;
  component_level: number;
  delta: number;
  required_capabilities: string[];
  guidance: Record<string, string>;
  issued_at: number;
  deadline_secs: number;
}

export interface NodeRuntimeAdapter {
  /** Current declared compatibility level of this Node node. */
  level: number;
  /** Capabilities this node has adopted. */
  capabilities: Set<string>;
  /** Called when the runtime issues a new challenge. */
  onChallenge(challenge: AdaptationChallenge): Promise<void>;
  /** Report the current level back to the Python core. */
  reportLevel(): Promise<boolean>;
}

/**
 * DefaultNodeRuntimeAdapter: automatically adopts all capabilities listed in
 * the challenge's required_capabilities and bumps its own level accordingly.
 */
export class DefaultNodeRuntimeAdapter implements NodeRuntimeAdapter {
  level: number;
  capabilities: Set<string>;
  private readonly client: NiblitClient;
  private readonly name: string;

  constructor(client: NiblitClient, initialLevel = 1.0, name = "niblit-node") {
    this.client = client;
    this.level = initialLevel;
    this.name = name;
    this.capabilities = new Set<string>([
      "state_portability",
      "knowledge_exchange",
    ]);
  }

  async onChallenge(challenge: AdaptationChallenge): Promise<void> {
    console.log(
      `[NiblitRuntimeAdapter] Challenge received: runtime=${challenge.current_runtime_level.toFixed(4)} our_level=${challenge.component_level.toFixed(4)} delta=${challenge.delta.toFixed(4)}`,
    );

    // Adopt every required capability listed in the challenge
    for (const cap of challenge.required_capabilities) {
      this.capabilities.add(cap);
      console.log(`[NiblitRuntimeAdapter] Adopted capability: ${cap}`);
    }

    // Advance our declared level to match the runtime
    this.level = challenge.current_runtime_level;
    console.log(`[NiblitRuntimeAdapter] Self-adapted to level ${this.level.toFixed(4)}`);

    // Report back to the Python core
    await this.reportLevel();
  }

  async reportLevel(): Promise<boolean> {
    try {
      await this.client.reportEnvCapabilities({
        component_name: this.name,
        declared_level: this.level,
        capabilities: Array.from(this.capabilities),
        runtime: "node",
        platform: `${process.platform}/${process.arch}`,
        node_version: process.version,
      });
      return true;
    } catch (err) {
      console.warn(`[NiblitRuntimeAdapter] reportLevel failed: ${err}`);
      return false;
    }
  }
}
