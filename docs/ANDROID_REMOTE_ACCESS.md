# Android access from another network

Prepared 30 October 2026. This configuration is NOT a live tunnel or APK.

## Design

Android HTTPS client -> Cloudflare named tunnel -> existing portal:8768 ->
authenticated scoped client APIs -> existing local inference/memory boundary.
The connector establishes outbound connections; no home-router inbound port
forwarding is required. A PC-hosted backend still needs this PC, Docker and its
network to stay on. Moving the connector/backend to persistent cloud compute is
the later availability step, not a feature of a tunnel itself.

Use a stable named tunnel and verified DNS hostname, proposed
`niblit-api.enginehsd.site`. A random temporary Quick Tunnel is not configured.
No tunnel account, DNS route, token or public endpoint has been created here.
Namecheap remains the recorded registrar; do not change nameservers, website or
mail records without reviewing the selected provider's actual DNS requirements.
If Cloudflare onboarding requires a DNS migration, plan/check all existing records
first. A private owner-only Tailscale connection is an alternative, requiring
the Android device to join the private network; it is not configured here.

## Implemented boundary

- `NIBLIT_PORTAL_REMOTE_ORIGIN` is empty by default. When enabled, it must be one
  exact HTTPS DNS origin without credentials, paths or ports.
- Remote Host selects the remote origin; writes require that exact Origin and
  the existing CSRF token. Proxy/forwarded headers never grant local privileges.
- Remote login cookies are Secure, HttpOnly and SameSite=Strict.
- Only client login/signup/session/chat/plans/workspace routes and static client
  assets are exposed. Local admin, research tools, learning controls and all
  unlisted routes are denied remotely, even for an administrator login.
- No MT5, Freqtrade, Lean, Qdrant, Docker, model-server or native-memory management
  port is routed by this tunnel profile. Native chat requests cannot request tools.
- Remote clients use the existing portal instance/task lock; a second model
  process or independent portal database is not started.

## Provisioning still required

1. Owner signs into the chosen tunnel provider and provisions a named tunnel and
   verified hostname. Review service terms and DNS changes in that account.
2. Save the tunnel token only in ignored private file
   `runtime/client-portal/cloudflare-tunnel-token`, never source, chat or Android.
   Restrict the file to the desktop owner. Rotate it if disclosed.
3. Configure exactly one public HTTP service route to `http://portal:8768`.
   Preserve the public Host header. Do NOT override Host or Origin to localhost;
   that would defeat the explicit remote-client distinction. No other routes.
4. Set `NIBLIT_PORTAL_REMOTE_ORIGIN` to the actual verified HTTPS origin.
5. Build the updated portal and combine compose.yml, compose.local-gguf.yml and
   compose.tunnel.yml, selecting profile `android-tunnel`. The ordinary local
   launch command does not include or activate the tunnel.
6. Verify the image/token-file interface and Docker configuration before starting
   the connector. Run a full acceptance from phone Wi-Fi AND mobile data.

Required acceptance: valid TLS; anonymous session denied; login/chat work; CSRF
and cross-origin rejection; revoked account denied; admin/learning/tool routes
return 403 remotely; private-workspace isolation; disconnection is visible;
no duplicate queued inference after reconnect. Check account abuse/rate limits,
Cloudflare access controls and backups before calling this production-ready.

## Android readiness

`deploy/android/` supplies an HTTPS-only client configuration and Android network
security template. The first shell should load the hosted same-origin client;
a bundled file:// UI has a different Origin and must not bypass server checks.
Native HTTP clients need a secure cookie jar and exact configured Origin on
mutations. Do not store passwords in plain preferences or bundle provider keys.
Next work is P8 in INTEGRATED_DELIVERY_PLAN.md: toolchain, Android app project,
device/emulator tests, debug APK, then owner-managed release signing.

## Rollback

Stop/remove ONLY the android-tunnel service. Recreate portal without the tunnel
override to remove the extra origin. Keep existing data volumes, accounts and
local model settings. Revoke/delete the provider route/token separately if the
owner no longer needs remote access. Do not remove unrelated DNS records.

Official references checked:
- https://developers.cloudflare.com/tunnel/get-started/
- https://developers.cloudflare.com/tunnel/reference/origin-parameters/
