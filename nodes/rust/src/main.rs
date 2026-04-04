// main.rs — Niblit Rust deployment node entry-point
//
// This node:
//   1. Connects to the Niblit Python core REST API
//   2. Exchanges cross-environment state (NiblitStateEnvelope)
//   3. Registers with the Niblit self-improving runtime
//   4. Provides a CLI that proxies commands to Niblit
//   5. Reports Rust environment capabilities back to the Python core

mod niblit_client;
mod niblit_state;

use clap::Parser;
use niblit_client::NiblitClient;
use niblit_state::NiblitStateEnvelope;
use serde_json::json;
use std::io::{self, BufRead, Write};

/// Niblit Rust Node
#[derive(Parser, Debug)]
#[command(
    name = "niblit-node",
    about = "Niblit Rust deployment node",
    version = "1.0.0"
)]
struct Cli {
    /// Message to send (non-interactive mode)
    message: Option<String>,

    /// Niblit API base URL
    #[arg(long, env = "NIBLIT_URL", default_value = "http://localhost:8000")]
    url: String,

    /// Optional API key (NIBLIT_API_KEY env var also accepted)
    #[arg(long, env = "NIBLIT_API_KEY")]
    api_key: Option<String>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    let client = NiblitClient::new(&cli.url, cli.api_key);

    // ── Health check ──────────────────────────────────────────────────────
    match client.health().await {
        Ok(h) => {
            eprintln!("[Niblit Rust] Connected to {} — status: {}", cli.url, h.status);
            if let Some(level) = h.runtime_level {
                eprintln!("[Niblit Rust] Runtime level: {:.4}", level);
            }
        }
        Err(e) => {
            eprintln!("[Niblit Rust] Could not reach {}: {}", cli.url, e);
            eprintln!("[Niblit Rust] Continuing in offline mode — state will be local only.");
        }
    }

    // ── State: pull from Python core or start fresh ────────────────────────
    let mut envelope = match client.pull_state().await {
        Ok(Some(env)) => env,
        _ => NiblitStateEnvelope::new(),
    };
    envelope.last_runtime = "rust".into();
    if !envelope.runtime_history.contains(&"rust".to_string()) {
        envelope.runtime_history.push("rust".into());
    }
    envelope.last_active_ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();
    envelope.seal();

    // ── Report Rust environment capabilities ──────────────────────────────
    let rust_caps = json!({
        "runtime": "rust",
        "platform": format!("{}/{}", std::env::consts::OS, std::env::consts::ARCH),
        "rust_version": env!("CARGO_PKG_VERSION"),
        "component_name": "niblit-node",
        "declared_level": 1.0,
        "capabilities": ["state_portability", "knowledge_exchange"],
    });
    let _ = client.report_env_capabilities(&rust_caps).await;

    // ── Single-command mode ────────────────────────────────────────────────
    if let Some(message) = cli.message {
        envelope.last_command = message.clone();
        envelope.total_commands += 1;
        match client.chat(&message, Some(&envelope.session_id)).await {
            Ok(resp) => {
                println!("{}", resp.response);
                envelope.last_response_snippet = resp.response.chars().take(200).collect();
                envelope.seal();
                let _ = client.push_state(&envelope).await;
            }
            Err(e) => {
                eprintln!("[Niblit Rust] Chat error: {}", e);
                std::process::exit(1);
            }
        }
        return Ok(());
    }

    // ── Interactive REPL ───────────────────────────────────────────────────
    eprintln!("[Niblit Rust] Interactive mode. Type 'exit' or Ctrl-C to quit.\n");

    let stdin = io::stdin();
    loop {
        print!("niblit> ");
        io::stdout().flush()?;

        let mut line = String::new();
        let bytes = stdin.lock().read_line(&mut line)?;
        if bytes == 0 {
            // EOF (Ctrl-D)
            break;
        }

        let input = line.trim().to_string();
        if input.is_empty() { continue; }

        if input == "exit" || input == "quit" { break; }

        // Local state dump
        if input == "state" {
            println!("{}", serde_json::to_string_pretty(&envelope)?);
            continue;
        }

        envelope.last_command = input.clone();
        envelope.total_commands += 1;
        envelope.last_active_ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();

        match client.chat(&input, Some(&envelope.session_id)).await {
            Ok(resp) => {
                println!("\n{}\n", resp.response);
                envelope.last_response_snippet = resp.response.chars().take(200).collect();
                envelope.seal();
                // Push every 5 commands
                if envelope.total_commands % 5 == 0 {
                    let _ = client.push_state(&envelope).await;
                }
            }
            Err(e) => {
                eprintln!("[Niblit Rust] Error: {}", e);
            }
        }
    }

    // ── Graceful shutdown: save state ──────────────────────────────────────
    eprintln!("\n[Niblit Rust] Saving state and disconnecting…");
    envelope.seal();
    let _ = client.push_state(&envelope).await;
    eprintln!("[Niblit Rust] Goodbye.");

    Ok(())
}
