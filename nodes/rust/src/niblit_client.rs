// niblit_client.rs — HTTP client for the Niblit Python REST API (Rust)

use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;

use crate::niblit_state::NiblitStateEnvelope;

#[derive(Debug, Clone)]
pub struct NiblitClient {
    base_url: String,
    api_key: Option<String>,
    client: Client,
}

#[derive(Debug, Deserialize)]
pub struct ChatResponse {
    pub response: String,
    pub session_id: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct HealthResponse {
    pub status: String,
    pub version: Option<String>,
    pub runtime_level: Option<f64>,
}

#[derive(Debug, Serialize)]
struct ChatRequest<'a> {
    message: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    session_id: Option<&'a str>,
}

impl NiblitClient {
    pub fn new(base_url: impl Into<String>, api_key: Option<String>) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(20))
            .build()
            .expect("failed to build HTTP client");

        Self {
            base_url: base_url.into().trim_end_matches('/').to_string(),
            api_key,
            client,
        }
    }

    fn url(&self, path: &str) -> String {
        format!("{}{}", self.base_url, path)
    }

    fn apply_headers(&self, builder: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        if let Some(key) = &self.api_key {
            builder.header("X-Niblit-Key", key)
        } else {
            builder
        }
    }

    // ── Health ──────────────────────────────────────────────────────────────

    pub async fn health(&self) -> anyhow::Result<HealthResponse> {
        let req = self.apply_headers(self.client.get(self.url("/health")));
        let resp = req.send().await?.json::<HealthResponse>().await?;
        Ok(resp)
    }

    // ── Chat ────────────────────────────────────────────────────────────────

    pub async fn chat(
        &self,
        message: &str,
        session_id: Option<&str>,
    ) -> anyhow::Result<ChatResponse> {
        let body = ChatRequest { message, session_id };
        let req = self
            .apply_headers(self.client.post(self.url("/chat")))
            .json(&body);
        let resp = req.send().await?.json::<ChatResponse>().await?;
        Ok(resp)
    }

    // ── State exchange ──────────────────────────────────────────────────────

    pub async fn push_state(&self, envelope: &NiblitStateEnvelope) -> anyhow::Result<bool> {
        let req = self
            .apply_headers(self.client.post(self.url("/api/state")))
            .json(envelope);
        let status = req.send().await?.status();
        Ok(status.is_success())
    }

    pub async fn pull_state(&self) -> anyhow::Result<Option<NiblitStateEnvelope>> {
        let req = self.apply_headers(self.client.get(self.url("/api/state")));
        let resp = req.send().await?;
        if resp.status().is_success() {
            let env: NiblitStateEnvelope = resp.json().await?;
            if env.verify() {
                Ok(Some(env))
            } else {
                eprintln!("[NiblitClient] State envelope checksum mismatch — ignoring");
                Ok(None)
            }
        } else {
            Ok(None)
        }
    }

    // ── Environment capabilities ────────────────────────────────────────────

    pub async fn report_env_capabilities(
        &self,
        caps: &Value,
    ) -> anyhow::Result<bool> {
        let req = self
            .apply_headers(self.client.post(self.url("/api/env/capabilities")))
            .json(caps);
        let status = req.send().await?.status();
        Ok(status.is_success())
    }
}
