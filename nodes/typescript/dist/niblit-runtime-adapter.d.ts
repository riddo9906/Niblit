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
export declare class DefaultNodeRuntimeAdapter implements NodeRuntimeAdapter {
    level: number;
    capabilities: Set<string>;
    private readonly client;
    private readonly name;
    constructor(client: NiblitClient, initialLevel?: number, name?: string);
    onChallenge(challenge: AdaptationChallenge): Promise<void>;
    reportLevel(): Promise<boolean>;
}
//# sourceMappingURL=niblit-runtime-adapter.d.ts.map