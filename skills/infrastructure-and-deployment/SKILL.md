---
name: infrastructure-and-deployment
description: Plan and operate Niblit's VPS, Docker, Tailscale, Supabase and deployment infrastructure where configured tools exist.
---
# Infrastructure and deployment

Use this skill for VPS, Docker Desktop, Tailscale, Supabase, hosting, networking and deployment tasks.

- First map the current topology: local Core, local GGUF Cloud, UI, Docker services, VPS endpoints and Tailscale connectivity.
- Prefer private connectivity through the user's configured Tailscale network. Do not expose local inference or admin endpoints publicly by default.
- Use Supabase only when the project has a configured Supabase project and supported credentials/connectors. Never invent project IDs or credentials.
- Before deployment, inspect Git status, current deployment, environment names and rollback path.
- Firewall, DNS, database migration, credential, deployment and service mutations require explicit one-time approval.
- Never print secrets or place credentials in source files, logs, command arguments or chat output.
- Verify health from the intended client path, including the Android-to-desktop route when relevant.
