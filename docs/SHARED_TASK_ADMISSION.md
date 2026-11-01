# Shared runtime task admission — P1 increment

The existing Memory Desk process on 8772 is the authority; no new daemon or
model process is created. A single SQLite row, acquired with BEGIN IMMEDIATE,
reserves the entire participating task. Host and Docker clients authenticate
with the existing private local-model service key. Tokens are hashed at rest;
neither prompts nor credentials are stored in the admission table.

Portal chat holds ownership through tool use, answer generation and durable
message storage. Local study holds it through recall, inference, assessment and
observation storage. Native RuntimeRouterV2, LocalBrainGateway.route_inference
and LlmToolLoop.chat have compatible opt-in wrappers. Nested calls in the same
logical Python context reuse ownership. Busy tasks return an error, not a queue.

The local Docker override enables NIBLIT_SHARED_ADMISSION=1 and uses
http://host.docker.internal:8772. Native callers opt in with the same flag and
default to http://127.0.0.1:8772. The private key file defaults to the existing
runtime/client-portal/gguf-api-key on the host; Docker uses its read-only secret.
Unknown endpoints/owners are rejected. Remote client routes cannot call the
authority or local owner tools.

Ambiguous network failures or interrupts quarantine ownership. A restart or
timer does not automatically release it while an old generation could remain
active. Ordinary local validation errors can finish ownership. If an acquire
response is lost, the durable reservation can remain blocked, safely.

## Owner recovery

Run `niblit-env/Scripts/python.exe scripts/runtime-task-status.py` for state only.
For recovery, stop Core, Cloud, Lean and portal request producers; verify no
other direct model clients remain. Then run the same script with `--recover
--confirm-producers-stopped`. It refuses recovery while known producer ports
are listening and, if GGUF is running, requires its authenticated slots endpoint
to show no active generation. It does not start services or trading. Never
register recovery as a model tool or automate a periodic reset.

## Native LocalBrain contract repair

RuntimeRouterV2 called a missing route_inference method. The gateway now exposes
that method without loading a model or spawning a process. Default Cloud mode
requires the exact requested local model to be registered; unavailable discovery
is an honest failure before generation. No paid/default-model fallback occurs.
An explicit NIBLIT_NATIVE_LOCAL_TRANSPORT=local_gguf can reuse the authenticated
portal GGUF transport when its local_gguf settings and key are configured.
OPENAI_MODEL was not changed. Network uncertainty during generation propagates
to shared admission rather than being hidden by another backend attempt.

## Evidence and limits

70 focused tests passed. Actual Windows host ownership rejected a competing
Docker acquisition, then released normally. An actual native Router -> LocalBrain
-> existing local GGUF call returned 4 for a synthetic arithmetic question, with
shared admission enabled and no paid calls/new model workers.

The full native Core, Cloud and Lean APIs were not listening at inventory time.
Their boot/lifecycle, frozen bundles and every legacy direct caller have NOT all
been migrated or accepted end-to-end. Cross-process delegation through a Cloud
server must keep one task owner; do not add independent nested admissions to the
downstream server without an explicit propagation contract. Continue tracing ALE
and legacy inference producers before declaring P1 complete.
