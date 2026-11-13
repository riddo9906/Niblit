# Real VPS deployment checkpoint

The SSH host fingerprint supplied through the user's VPS console was matched before connecting.
Key-based Administrator access was verified. Windows Server 2025 build 26100, 2 logical CPUs and
approximately 6 GB RAM were observed. The virtual disk is 120 GiB. Its C: partition initially used
approximately 80 GiB and was grown online to approximately 120 GiB after verifying its layout.
Approximately 90 GiB was free at the last check.

All firewall profiles are enabled. Dedicated SSH and RDP rules restrict access to the currently
verified source addresses. SSH password authentication is disabled and public-key access was retested.
Forwarding is restricted to the gateway loopback endpoint. Defender antivirus and real-time protection
were observed enabled. Time synchronization reported time.windows.com and a successful sync.

Signed Python 3.14.10 x64 was installed in C:/NiblitGateway/python. The initial installer invocation
failed with MSI 1603 due to a malformed target path. The corrected absolute path was installed and
verified. Gateway source was checksum-verified and expanded into an independent versioned release.
MetaTrader5 5.0.6231 and NumPy 2.5.4 were installed with pinned SHA-256 hashes. Thirteen gateway tests
passed on the real VPS in 1.481 seconds using broker doubles. This does not establish XM connectivity.

The 0.1 installer script assumes Python 3.12. The verified remote installation uses the dedicated
3.14.10 executable to create the release .venv, then pip --require-hashes with requirements.lock.
Private read/stop tokens were generated only inside ACL-restricted VPS state. They were not printed,
copied into the repository or placed in this evidence. The gateway is staged and deliberately stopped
until the broker-sourced account binding is available. The funded mutation interface remains disabled.

The official XM website denied automated installer retrieval. The user has been asked to install
XM MT5 inside RDP and sign in directly. An interactive-session probe script is staged on the VPS.
No default terminal, configured account metadata or paid subscription is treated as broker proof.

## Desktop performance contribution

Keep Core, inference, research, learning and six-strategy analysis on the existing desktop.
The VPS handles MT5 and bounded read-only observation. Small timestamped observations cross the
authenticated tunnel. This reduces VPS workload rather than pooling desktop CPU or RAM into Windows.
Desktop outages do not grant new execution authority. Broker-side protection remains independent.
No remote inference or live desktop integration is claimed yet.

## Recovery and next checks

Keep the deployment key protected by the desktop Windows ACL and retain the verified known_hosts file.
Provider-console recovery must be maintained if the desktop public IP changes and source rules need updating.
The dedicated nonadministrator runtime identity, actual Windows update/reboot acceptance, off-server backups,
MT5 process/session acceptance, authenticated live tunnel and actual Core/Market Desk readback remain pending.
Do not clear persistent emergency stops or replace broker state during rollback.
