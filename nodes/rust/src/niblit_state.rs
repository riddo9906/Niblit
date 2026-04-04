// niblit_state.rs — Portable state envelope for Rust
//
// Mirrors the Python NiblitStateEnvelope schema and env_state.py exactly.
// Any Rust component that exchanges state with the Niblit Python core must
// use this struct.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NiblitStateEnvelope {
    // Identity
    pub session_id: String,
    pub niblit_version: String,

    // Runtime provenance
    pub origin_runtime: String,
    pub origin_platform: String,
    pub last_runtime: String,
    pub runtime_history: Vec<String>,

    // Session counters
    pub total_commands: u64,
    pub total_facts: u64,
    pub total_interactions: u64,

    // Knowledge snapshot
    pub known_topics: Vec<String>,
    pub knowledge_summary: String,

    // Last active state
    pub last_command: String,
    pub last_response_snippet: String,
    pub last_active_ts: f64,

    // Environment capabilities
    pub env_capabilities: HashMap<String, serde_json::Value>,

    // Runtime-specific extras
    pub extras: HashMap<String, serde_json::Value>,

    // Integrity
    pub checksum: String,
}

impl NiblitStateEnvelope {
    /// Create a fresh envelope for the Rust runtime.
    pub fn new() -> Self {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();

        let os_info = format!(
            "{}/{}",
            std::env::consts::OS,
            std::env::consts::ARCH
        );

        Self {
            session_id: Uuid::new_v4().to_string(),
            niblit_version: "1.0".into(),
            origin_runtime: "rust".into(),
            origin_platform: os_info.clone(),
            last_runtime: "rust".into(),
            runtime_history: vec![],
            total_commands: 0,
            total_facts: 0,
            total_interactions: 0,
            known_topics: vec![],
            knowledge_summary: String::new(),
            last_command: String::new(),
            last_response_snippet: String::new(),
            last_active_ts: now,
            env_capabilities: HashMap::new(),
            extras: HashMap::new(),
            checksum: String::new(),
        }
    }

    /// Compute the 16-char SHA-256 prefix checksum (same algorithm as Python).
    pub fn compute_checksum(&self) -> String {
        // Build a copy without the checksum field, then sort keys via JSON
        let mut map = serde_json::to_value(self).unwrap_or_default();
        if let Some(obj) = map.as_object_mut() {
            obj.remove("checksum");
        }
        let raw = serde_json::to_string(&Self::sort_value(map)).unwrap_or_default();
        let hash = Sha256::digest(raw.as_bytes());
        hex::encode(hash)[..16].to_string()
    }

    /// Seal: compute and store checksum in place.
    pub fn seal(&mut self) {
        self.checksum = self.compute_checksum();
    }

    /// Verify the stored checksum.
    pub fn verify(&self) -> bool {
        self.checksum == self.compute_checksum()
    }

    /// Recursively sort object keys (matches Python's json.dumps sort_keys=True).
    fn sort_value(v: serde_json::Value) -> serde_json::Value {
        match v {
            serde_json::Value::Object(map) => {
                let mut sorted: serde_json::Map<String, serde_json::Value> =
                    serde_json::Map::new();
                let mut keys: Vec<String> = map.keys().cloned().collect();
                keys.sort();
                for k in keys {
                    sorted.insert(k.clone(), Self::sort_value(map[&k].clone()));
                }
                serde_json::Value::Object(sorted)
            }
            serde_json::Value::Array(arr) => {
                serde_json::Value::Array(arr.into_iter().map(Self::sort_value).collect())
            }
            other => other,
        }
    }
}

impl Default for NiblitStateEnvelope {
    fn default() -> Self {
        Self::new()
    }
}
