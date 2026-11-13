# Hybrid desktop deployment — 2026.11.12-hybrid1

Core, market intelligence, strategies, cognition, canonical SQLite/outbox, MT5/MQL5, Tauri and native llama.cpp remain the existing Windows runtime. Portal, Qdrant and Freqtrade remain containers. This increment packages the existing portal; it does not introduce a second Core or inference authority. Shared schemas: `contracts.json`. Detailed plan and audit: task `work/market-fabric/CONTAINER-PLAN.md` and `outputs/NIBLIT_CONTAINER_NATIVE_AUDIT.txt`.

## Safe development workflow

Run from the Niblit repository in PowerShell:

```powershell
./deploy/hybrid/Build-Hybrid.ps1
docker compose -f deploy/hybrid/compose.yml --profile development up -d portal-development
docker compose -f deploy/hybrid/compose.yml --profile development ps
docker compose -f deploy/hybrid/compose.yml logs --tail 100 portal-development
```

Development portal: http://127.0.0.1:8879. It uses separate development data/backups. Existing portal stays on 8769. The existing local model key is mounted read-only as a Docker secret; never put it in an image, command argument or repository. Native model 8766 and memory/admission 8772 must be available for authenticated model/memory requests; UI health alone does not prove them. Background portal learning is disabled. Native market observation keeps working if containers or VPS are unavailable.

The base image ID in `base-image.id` and installed dependency lock identify the audited pre-existing Python runtime. Build networking is disabled. A fixed SOURCE_DATE_EPOCH and deterministic export produced identical digests in two local builds: `sha256:90f7edef286b7261b2fdbcb5a817a8d11546a6e1ec052b3817d4fdf1ef80a04d`. The exact app/base images are exported in the task's `outputs/Niblit-Hybrid-Portal-2026.11.12.tar`; `docker image load -i PATH_TO_ARCHIVE` restores them on another compatible host before the build script verifies the base ID. No registry credentials or image push are required. Source is explicitly allowlisted by `Dockerfile.dockerignore`; private dotenv, databases, keys and models are excluded. Mounted runtime data and secrets are not part of the image export.

## Production-like profile

`--profile production-like up -d portal-production` reuses external `niblit-client-cloud_portal-data` and `portal-backups` and binds 8769. **Do not run while the original portal owns that port or writes those volumes.** Back up and validate portal databases, coordinate the cutover, stop only the original portal, then start the candidate. This cutover has not been accepted. Rollback stops the candidate and starts `niblit-client-cloud-portal-1`; retain durable data and assess schema compatibility. Never restore an older database blindly after new writes.

Qdrant is deliberately not a service in this Compose file: the existing `niblit-memory-lab-qdrant-1` and `niblit_memory_qdrant` remain authoritative. No new Qdrant or Ollama is created. Do not run the generic portal Compose defaults, which contain a second Qdrant version and Ollama. Do not use `down -v`, delete/recreate volumes or upgrade Qdrant without validated collection snapshots and explicit approval. Dedicated internal backend plus native-access networks, non-root user, read-only root, bounded tmpfs, CPU/memory/PID limits, capped logs and health/restart policies are configured.

## Backup and restore

```powershell
./niblit-env/Scripts/python.exe scripts/hybrid-backup.py backup runtime/memory-framework/ledger.sqlite3 C:/NiblitBackups
./niblit-env/Scripts/python.exe scripts/hybrid-backup.py restore-new C:/NiblitBackups/VALIDATED.sqlite3 C:/NiblitRestore/ledger.sqlite3
./niblit-env/Scripts/python.exe scripts/hybrid-qdrant-backup.py --config .env.memory-laboratory --directory C:/NiblitBackups/qdrant
```

Online SQLite backup uses a pinned snapshot, integrity check and SHA-256 manifest. A `.partial` file is not a backup. Restore requires a fresh path and matching manifest; test against a separate runtime before any coordinated replacement. The actual canonical restore matched the backup hash and retained 125,695 records, 61,083 outbox rows and 288 task authorizations. Keep at least one encrypted off-desktop copy using the user's chosen destination; no cloud credentials are assumed. Model artifacts remain native; record hashes and retain the original model file.

All five Qdrant snapshots were downloaded with provider checksum verification and restored into the separate `niblit_hybrid_restore_validation_20261112` test volume. Counts matched; all collections reached green; nonempty collections passed vector self-queries and sampled source-record hash comparisons. The validation container is stopped; the test volume is retained. The original Qdrant volume was not replaced. The first undersized test storage failed optimizer readiness, so use adequate Docker-managed disk storage rather than a small tmpfs. Snapshot creation succeeded before an interrupted HTTP connection; `--resume-latest` resumed completed downloads without blindly repeating creation. Validate saved manifests/checksums before reusing them.

These independently timed backups are not an atomic cross-store recovery checkpoint. Canonical SQLite remains authoritative; reconcile/replay its outbox after any coordinated restore. Production restore/upgrade remains a separate approval/cutover boundary. Do not copy a live Qdrant volume as a substitute for its supported snapshot API.

## Kubernetes preparation

`kubernetes.yaml` contains a single-replica/Recreate portal, ClusterIP service, restricted workload identity, resource limits, probes and default-deny network policy. It does not provision Qdrant, a cluster or PVCs. Offline contract tests pass; Kubernetes API validation and runtime acceptance are pending. Replace documentation address `192.0.2.1` with the approved private native bridge, configure TLS/private transport, distribute the validated image, and provision existing-data PVC references and the secret through the user's secret manager before a separately authorized deployment. Do not apply these manifests as-is.

Funded execution remains disabled. Container restarts grant no trading authority. Existing canonical session/order IDs, reconciliation and circuit breakers remain the only broker command path; this portal candidate has not proven a containerized broker lifecycle.

Implementation references: [Qdrant 1.18 snapshot creation](https://api.qdrant.tech/v-1-18-x/api-reference/snapshots/create-snapshot), [isolated snapshot recovery](https://api.qdrant.tech/v-1-18-x/api-reference/snapshots/recover-from-snapshot), [BuildKit reproducible builds](https://github.com/moby/buildkit/blob/master/docs/build-repro.md).
