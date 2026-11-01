# Cloud portal package

This minimal container is the client service, not the full Windows Niblit desktop.
Choose a persistent Docker host with a mounted `/data` volume and an HTTPS proxy.
Set `NIBLIT_PORTAL_ORIGIN` to its exact public HTTPS origin. Keep one instance.
Build from the Niblit repository root:

```text
docker build -f deploy/client-portal/Dockerfile -t niblit-client-portal .
```

Set up the first admin using the same volume in an interactive one-off container
with `python scripts/run-client-portal.py --create-admin`. No passwords belong
in build arguments or the image. A persistent volume and that admin setup are
required before client use. The portal image is built locally; no cloud deployment
or purchase has occurred. The local acceptance listener is 127.0.0.1:8769.

The responder supports loopback Ollama or the private `ollama:11434` Compose
service. It rejects arbitrary remote provider URLs and has no paid fallback.
Model weights are not included/downloaded by the portal-only acceptance build.
Do not expose the PC's Ollama or Niblit private APIs publicly.

The existing repository-root render.yaml describes an older broad deployment
with autonomous loops and provider credentials. It is not this portal profile;
do not use it for the client service. The explicit Docker COPY allowlist and its
Dockerfile-specific ignore file keep private runtime data out of this image.

Vercel can host the marketing/front-end portion, but this implementation's SQLite
file and process-local turn lock require a persistent single-instance host. A
serverless conversion would require external durable storage and distributed
coordination; moving files alone is insufficient.

## Compose layout

### Existing Windows GGUF model (local portal repair)

Use `Start-Client-Portal.cmd` from the repository root with Docker Desktop running.
It starts the already-installed Qwen 2.5 Coder 3B GGUF through the installed
llama-server binary and applies `compose.local-gguf.yml`. The service listens on
host loopback port 8766, uses two CPU threads and one slot, and reads its private
API key from ignored `runtime/client-portal/gguf-api-key`. The container mounts
that file as a read-only Docker secret. No model download or paid fallback.

The authenticated `/api/model-status` endpoint checks actual model availability,
independently of login/database health. The UI disables chat sending until ready.
Replies and history are bounded to fit a 4096-token runtime context. Account
controls remain available if inference stops. Refresh the browser after updating.

Local acceptance passed through login → model readiness → message POST → actual
GGUF reply → stored assistant history, using a temporary test database. Your
own account/password/conversation were not used by the test. Cloud deployment
still needs its separate durable database and production connector responder;
this Windows local model repair is not a Vercel-hosted model.

`compose.yml` prepares one persistent Docker host:

- Portal UI/API together, preserving same-origin authentication and CSRF.
- `portal-data`: accounts, roles, workspace membership, quotas and conversation SQLite.
- `portal-backups`: consistent SQLite backups, also requiring off-host copies.
- Private Qdrant and `qdrant-data` volume. Client vector retrieval and tenant
  namespaces are not integrated here; desktop personal memory is not imported.
- Private Ollama and `ollama-models` volume; weights need a separate download/test.
- Optional public Caddy HTTPS profile with persistent certificate volumes.

Versions resolved from official release metadata on 2026-10-30: Qdrant 1.20.0,
Ollama 0.40.13, Caddy 2.11.7. These services are not started by portal-only checks.

```text
docker compose -f deploy/client-portal/compose.yml build portal
docker compose -f deploy/client-portal/compose.yml up -d --no-deps portal
docker compose -f deploy/client-portal/compose.yml exec portal python scripts/run-client-portal.py --create-admin
```

The last command asks for the administrator name/password locally. No default
password exists. Signup remains pending until approved; email verification/reset,
billing and production abuse controls are not implemented. One instance only.

## Future cloud rollout

Use a persistent Docker server after one has been obtained. Vercel hosts the
company website separately. Proposed client hostname: `portal.enginehsd.site`.
Copy `.env.example` to private `.env` in this folder and set the exact HTTPS
origin/domain. Point only the portal DNS record to the new server, preserving
apex Vercel records, email and other unrelated DNS.

```text
docker compose --env-file deploy/client-portal/.env -f deploy/client-portal/compose.yml --profile public up -d --build
docker compose --env-file deploy/client-portal/.env -f deploy/client-portal/compose.yml exec ollama ollama pull qwen2.5-coder:3b
```

The second command is a substantial model download. Test server capacity and
model-backed replies before inviting clients. Verify TLS, login, signup approval,
private workspace isolation, revocation and recovery. Then add the company site's
portal link. No cloud account, server or public service has been provisioned.
MT5 desktop IPC and broker authority do not move into this Linux portal.

## Backups

Named volumes survive container replacement on the same host, not host-disk loss
or explicit deletion. Never use `down -v` or volume pruning on production data.

```text
docker compose -f deploy/client-portal/compose.yml exec portal python scripts/backup-client-portal.py
```

This uses SQLite's backup API and verifies integrity. Copy completed files from
`/backups` to encrypted off-host storage. Use Qdrant's native snapshots for vector
collections; copying a live storage directory is not a consistent snapshot.
Restore tests should use a separate volume first. Stop the service before any
real restore, preserve a rollback copy, restore ownership and verify isolation.
No destructive restore is automated here.

Reference: https://docs.docker.com/engine/storage/volumes/
