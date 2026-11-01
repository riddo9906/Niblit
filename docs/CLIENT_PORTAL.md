# Shared Niblit client portal

This is an isolated, invite-only shared conversation hosted by one server process.
All authorized members of the selected workspace see that conversation. It does not export the desktop
Core session, private KnowledgeDB/Qdrant namespace, workspace files or trading tools.
Its durable conversation is the initial shared-session memory; semantic Qdrant
projection and manager tools are not connected yet.

## Start locally

From the Niblit repository, run the following once in an interactive terminal.
The password is requested privately and is stored as a salted scrypt hash.
There are no default accounts. Public sign-up creates a pending request only;
an administrator must approve it before the applicant can read the shared session.
Approved applicants start as viewers. Revoked accounts cannot reactivate or reset
their password through sign-up. Password recovery and email verification are not
implemented; usernames are account labels, not verified identities.

```powershell
.\niblit-env\Scripts\python.exe scripts/run-client-portal.py --create-admin
.\niblit-env\Scripts\python.exe scripts/run-client-portal.py
```

Open http://127.0.0.1:8768. Administrators can create and revoke accounts in
the portal. Operators can send messages; viewers can read. Membership revocation
invalidates existing login sessions immediately. Login cookies expire after eight
hours. The session history and audit trail persist in
`runtime/client-portal/session.sqlite3`; protect this directory and back it up.
Members must understand their messages are shared with other members.

## Private pilot tiers

The server administrator manually assigns tiers; no payment or subscription is
connected. Personal allows one private workspace and 50 requests/day; Pro allows
three and 250 requests/day; Team allows five, up to five seats per workspace
including the owner, and 500 requests/day. These are initial pilot limits, not
priced commercial plans. Attempts count even if inference fails, to bound load.
Limits aggregate across an owner's private workspaces and reset at 00:00 UTC
(02:00 South Africa). Existing shared-session messages remain shared after migration.

Private workspace owners can chat even if their shared-session role is viewer.
Team owners can add already-approved accounts as viewers or operators, inspect
membership and revoke it. A client cannot assign its own tier or gain access by
guessing a workspace identifier. History and model context are filtered by the
server. The server administrator is not automatically a private workspace member;
however, this is not end-to-end encryption: whoever administers the host/database
can access stored data. Qdrant integration, export/deletion workflows, billing,
password recovery, verified email identities and production security review remain
outstanding. Use a persistent server for this SQLite/single-worker implementation.

## Local model

The responder calls Ollama at 127.0.0.1:11434 with `qwen2.5-coder:3b`, bounded
context and output. No OpenAI key or cloud fallback is used. Ollama and this model
must be installed and running. This connection has not yet been proven against
the installed runtime. If unavailable, the UI records the failed request without
retrying. Tests inject a deterministic responder and incur no inference charges.

## External deployment

Keep the Python listener on loopback. Put a maintained HTTPS reverse proxy on
the same server in front of port 8768, using a dedicated hostname such as a
client subdomain that you control. Start with `--origin https://YOUR-HOSTNAME`.
The proxy must preserve that exact Host header and enforce request-body limits
(16 KB), connection limits and rate limiting on `/api/login` and `/api/signup`.
Do not forward the private Core, trading desk, Ollama, Docker or Qdrant ports.
The public marketing site does not act as this server or a login backend.

External routing, HTTPS, backups and local-model acceptance are outstanding;
the gateway is not yet exposed to external users. No DNS change was made for a
client subdomain. Use one process/worker: turns are serialized within that process.
Multi-process inference coordination and larger-scale account management are
future work. Sessions deliberately share all messages; use separate deployments
for clients who must not see each other's information.

## Validation

`tests/test_server_manager.py` covers durable shared history, roles, CSRF/origin
checks, immediate revocation, expiry, failed-login throttling and concurrent-turn
rejection. This does not establish production hosting readiness or an end-to-end
model response. No default administrator password was generated or saved.
