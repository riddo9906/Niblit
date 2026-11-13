# Niblit VPS Gateway 0.1

A standalone Windows observation gateway for one XM MT5 account. MT5 and this gateway run in the VPS user's interactive Windows session. Strategy evaluation, inference, memory, and Market Desk stay on the desktop. The desktop client is a status and stop utility. Integration into Core and Market Desk is pending.

## Authority and status

| Surface | Behavior |
| --- | --- |
| GET /health | Authenticated process liveness |
| GET /status | Effective config, readback freshness, durable breaker, last verified inventory, funded denial, and operation-by-operation authority. HTTP 503 when broker readback is unavailable or stale. HTTP 200 means fresh observation and can coexist with a latched breaker. |
| POST /emergency-stop | Commits a persistent stop and audit event before acknowledging. No body. The stop survives restart and takes precedence over reconciliation. |
| Broker operations | Open, modify, close, cancel, and switch account are disabled in code. There is no remote reset route. |

The gateway reads one strict JSON profile and one separate operator token file. Unknown and duplicate profile keys fail startup. The process ignores Niblit dotenv profiles, MCP settings, and execution flags. Authenticated status includes the effective terminal path and account identifiers. Treat status and the SQLite ledger as private.

Each probe uses the explicit MT5 executable and checks terminal install path, terminal data identity, broker company, login, server, account mode, and currency. It reads positions and pending orders and verifies identity again before accepting the result. XM server naming is a discovery sanity check. The operator must independently compare the discovered account and install against the terminal UI and Journal. MT5 may launch the configured terminal during initialization and uses its existing selected account. See [MetaQuotes initialize](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py) and [account info](https://www.mql5.com/en/docs/python_metatrader5/mt5accountinfo_py).

The r9.1 funded evaluator is included unchanged. Gateway monitoring has no funded policy or trade proposal and always produces a funded rejection. Separate local checks use decimal equity and margin, configured limits, position count, and stop presence. Any observed inventory is unowned by this release. Inventory changes, unowned inventory, missing stops, limit breaches, failed broker reads, and observed freshness gaps latch reconciliation. A successful later probe refreshes the evidence while leaving the latch in place. SQLite commits the inventory, reasons, and breaker together. This is current-inventory reconciliation, with no deal-history backfill or unknown-order outcome matching. The journal grows over time. Back up the SQLite file with the gateway stopped and plan disk retention before a sustained run.

## Setup after provisioning

1. Use a supported 64-bit Windows Server with a desktop session and dedicated Windows user. Install XM MT5 and 64-bit Python 3.12. Open the intended XM terminal in the dedicated user's session and verify its active account and network status in the Journal. Use investor access if available for the account. Keep algorithmic and external Python trading disabled in MT5. Enter any broker sign-in only in MT5.
2. Copy this project to a new directory in the VPS user's profile. Open PowerShell in that directory. Select an exact reviewed MetaTrader5 wheel version for Windows x64 and run the installer. It creates a private virtual environment and runs the broker-double tests.

   ~~~powershell
   $version = Read-Host 'Exact reviewed MetaTrader5 version'
   .\Install-Gateway.ps1 -Mt5Version $version
   $terminal = 'C:\Program Files\XM MT5\terminal64.exe'
   .\.venv\Scripts\python.exe -B .\broker.py $terminal
   ~~~

3. Copy gateway.example.json to gateway.json. Replace terminal with the exact installed path and account with the complete discovery result after comparing it to the UI and Journal. Confirm the local monitoring thresholds in account currency. The sample starts with zero positions and zero margin allowed. Keep gateway.json outside source control.
4. Create a fresh private state directory in the VPS user profile. Check its ACL and ensure only the gateway user, SYSTEM, and authorized administrators have access. Then generate the token on the VPS. The following prints only the file path.

   ~~~powershell
   $state = Join-Path $env:LOCALAPPDATA 'NiblitGateway'
   New-Item -ItemType Directory -Path $state -ErrorAction Stop | Out-Null
   icacls $state
   ~~~

   After checking the ACL, run:

   ~~~powershell
   .\.venv\Scripts\python.exe -c "import pathlib,secrets,sys; p=pathlib.Path(sys.argv[1])/'operator.token'; p.open('x',encoding='ascii').write(secrets.token_hex(32)); print(p)" $state
   .\Start-Gateway.ps1 -Config .\gateway.json -StateDir $state
   ~~~

   Run from the same interactive user session as XM. Disconnect the remote desktop session while keeping the user signed in. For restart automation, use an at-logon scheduled task configured to run only when that user is logged on, with full paths and one instance. Test disconnect, sign-out, and reboot behavior before relying on unattended observation.

5. On the VPS, enable Windows OpenSSH using the Microsoft instructions. Limit inbound SSH to the desktop's trusted network or VPN in both Windows and provider firewalls. Use a dedicated non-admin key-authenticated SSH identity, disable password authentication for it, and restrict TCP forwarding to the gateway loopback destination where supported by the installed OpenSSH build. Verify the VPS host key fingerprint through its console before adding it to the desktop known-hosts file. Leave TCP 18765 closed to inbound traffic. Securely copy operator.token to an ACL-protected location on the desktop over verified SSH or a trusted administrative channel. Keep the desktop private key and token separate. [Install Windows OpenSSH](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse) · [Configure key authentication](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement)

6. From the trusted desktop, keep this SSH command running in its own window and use the client from a second PowerShell 7 window. Replace the SSH destination and token path. If changing the local port, also pass that port to the client.

   ~~~powershell
   ssh -N -T -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=2 -L 127.0.0.1:18765:127.0.0.1:18765 gatewayuser@your-vps
   .\Read-Gateway.ps1 -TokenFile C:\private\operator.token -Action health
   .\Read-Gateway.ps1 -TokenFile C:\private\operator.token -Action status
   ~~~

   SSH supplies encryption and host/client authentication between machines. HTTP and bearer authentication are confined to loopback at both ends. Use the desktop client only while the verified forward is active. Any holder of the bearer token who can reach the listener can read status and latch a stop. Run this on trusted hosts with restricted local access. To latch the stop, run the same client with -Action emergency-stop. A failed request or lost response requires status readback after reconnecting. An authenticated stop does not alter broker positions or pending orders.

7. Before accepting the VPS, verify the exact bound account, terminal path, fresh status, closed public gateway port, and unavailable order routes. Verify disconnect and recovery on a demo or an isolated test environment. Compare both inventories with MT5. Confirm the emergency latch survives gateway restart on a separate acceptance state directory. A production-state latch has no reset in this version. Preserve its database and investigate before provisioning fresh observation state.

## Offline policy

A desktop or tunnel disconnect leaves the VPS observer polling while all broker mutations remain disabled. A VPS-to-broker disconnect or stale snapshot makes current status unavailable and retains the last verified inventory for incident review. Treat that inventory as historical until confirmed again. Existing positions and pending orders remain under broker and operator control. Previously confirmed broker-side protection remains the only automated protection this design relies on. The gateway will never create or repair stops, cancel pending orders, close positions, or adopt a position based on cached desktop intent. Use the broker's normal operator channel for manual action when required. There is no order queue or reconnect replay.

## Local evidence and remaining gates

- Inspected Core 1b40c411, UI 4425a4b, Cloud c6f2291, and Lean bfa656e. Found 49, 1, 6, and 3 tracked modified files respectively. Inspected the canonical context map, MT5 bridge and session wiring, funded evaluator, package layout, r9.1 release evidence, and the supplied dotenv audit. The gateway is isolated from those checkouts and release directories.
- The four r8 processes were observed with the same PIDs before and after implementation. Process observation establishes continuity only.
- The saved r9.1 evidence describes a frozen candidate that passed packaged synthetic checks. Its XM IPC attempt timed out. This project has not verified XM identity, contract specifications, fees, or broker-side protection.
- See TEST-RESULTS.txt for the local Windows test run. VPS provisioning, SSH/firewall acceptance, installer testing with the selected wheel, and real MT5 IPC/readback in the intended Windows session are pending. The desktop observer adapter, deal-history recovery, and any funded acceptance are separate work.
- The copied funded_risk.py SHA-256 is 12AD035C85DAFD3250D54E75E6CA5D82D26E2993AE3A9EE78E978FB9B19CBCA3.
## Optional Exness demo extension (0.3.3)

The original XM observation routes and database remain read-only. A separately
configured `--demo-config` enables authenticated `/demo/` RPCs for the existing
Core demo-session/ticket implementation. It requires exact SDK demo identity,
an explicit terminal, a distinct protected credential, and a separately pinned
desktop `NIBLIT_EXNESS_DEMO_PROFILE`. Omitting that profile registers no demo
adapter. No strategy runs on the VPS, no account is switched, and no session
is automatically activated or renewed.

See `docs/architecture/EXNESS_REMOTE_DEMO_ACCEPTANCE.md` in the main repository
for the actual release paths, tests, operational limitations and rollback.
BTCUSDm is capped at 0.01 lots and one reviewed entry in the operator UI;
ETHUSDm's broker minimum exceeds that ceiling. SNXUSDm is broker-disabled.
The remote crypto review allowance explicitly uses the greater of 20 broker
points and one basis point of price; cash risk and protection checks remain.
Existing desktop demo orders retain their default review policy. Funded
submission, modification, cancellation, closure and account switching remain
disabled. Current values must come from fresh account-bound broker readback.
