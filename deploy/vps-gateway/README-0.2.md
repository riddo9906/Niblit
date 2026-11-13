# Gateway 0.2 source candidate

This directory evolves the recovered 0.1 source. Remote deployment and funded XM readback remain pending.
The baseline ZIP and original source are retained in the Codex session outputs.
The 0.2 gateway adds ticket-indexed order/deal history, transactional checkpoints, five-minute overlap,
separate stop authority and persistent replay rejection. Initial history starts 24 hours before first probe.
Status returns the latest 100 orders and 100 deals. SQLite retains the retrieved history.
Full account-history backfill and durable desktop event synchronization remain pending.

Use the existing installation and startup scripts after provisioning. Before first launch, create
independent 32-byte random hex secrets in operator.token and stop.token in the ACL-restricted state
directory. Core receives only operator.token. Read-Gateway.ps1 uses operator.token for observations
and stop.token for emergency-stop. Every stop request includes a unique UUID and fresh timestamp.
The endpoint rejects reused UUIDs. A retry with a new UUID is safe because the stop is a latch.

The production probe requires exactly one process at the explicit terminal executable in the same
Windows session as Python before calling the SDK. It never intentionally starts a missing terminal.
A process can exit between inspection and SDK attachment; verify process behavior on the actual VPS.
MT5 IPC initialization is bounded at five seconds, with an outer ten-second subprocess deadline.

On the desktop, copy core-profile.example.json to a private profile and fill only broker-verified
identity values. Select it with NIBLIT_VPS_GATEWAY_PROFILE in the intended new Core process environment.
The existing Core sessions status route consumes RemoteBrokerGateway. Market Desk's existing sessions
panel shows remote state and hides the remote observation when unavailable. The client has bounded
HTTP reads, explicit timeouts, a short request cache, bounded retry backoff and no broker mutation API.
It requires the operator-verified SSH loopback forward described by the baseline README. A loopback
port alone does not prove SSH host identity. Capture SSH acceptance separately.

The original gateway.json example is a deliberately invalid demo placeholder. Use the actual XM
readback to create the live-bound profile. Do not copy placeholders into operational state.
The original README describes 0.1. Follow this file for the 0.2 token and history changes.

Tests use broker doubles and real local HTTP servers. They do not establish VPS or XM acceptance.
No runtime profile was activated and no existing release was rebuilt or overwritten.

Operational HTTP logs record status, timestamp and request ID without credentials or broker payloads.
They rotate at 2 MB with three backups. The canonical SQLite journal requires a separate retention
and off-server backup policy. It is retained for reconciliation and is never treated as a rotating log.
