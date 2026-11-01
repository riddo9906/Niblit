# Local model research and improvement loop

The administrator can select **Use owner research tools** on an individual portal
message. Ordinary client chat has no tools. Inference stays on the configured
local Qwen service; there is no paid fallback or unattended background agent.

## What, how and why

1. The local model selects a tool using a small JSON planning protocol. The host
   validates the exact name, argument keys, value types and turn budget.
2. `source_list` and `source_read` expose a small published portal source snapshot,
   with hashes. They do not expose the desktop repository, credentials or memory.
3. `docs_read` retrieves one of five official documentation pages. Only fixed
   catalog URLs are permitted. No arbitrary URLs, searches, redirects, cookies,
   API keys or user query text go to the internet. Responses have time/byte/text
   limits and source hashes. Web text is untrusted reference data.
4. `proposal_save` records rationale, draft patch and suggested validation in the
   existing persistent SQLite volume. A draft is not an applied change or a
   successful test. Review it before implementation using the development tools.
5. The model receives observations and answers, or stops at three tools/four
   generations. Invalid decisions stop safely. There are no retries after a
   restart. Running actions become interrupted in the activity log.

Every executed action records actor, workspace, originating message, arguments,
status, observation and time. The administrator can inspect these while the turn
runs. Membership and administrator activation are checked for every invocation.
Tool events and proposals are only returned for the selected authorized workspace.

## Limits and next stage

## Bounded local tutor

The local administrator can start a three-question idle study session. Chat and
study share one task lock for the entire feedback loop; busy work is rejected,
not queued. Study waits for 60 seconds of chat inactivity, waits 120 seconds
between questions and expires after 15 minutes. Stop prevents another question;
an in-flight generation can finish. Sessions never resume after a restart.

The sequence is memory recall, one local-model question, citation check, durable
assessment, and an optional **unverified episodic observation** in native memory.
Missing evidence skips inference. Missing citations records a knowledge gap.
References being present does not prove truth: candidates remain unverified.
Prior generated reflection observations are excluded from future study evidence
to prevent the model's own claims becoming self-confirming facts.

The bridge uses the existing governed memory gateway and permissions. It cannot
choose another namespace, verify a fact, delete evidence, change code or trade.
Native KnowledgeDB and trading evidence are studied through their existing
projection into the source ledger/Qdrant; this does not invent coverage for
information that has not been projected. Source memory stays out of shared chat.

This bridge is local-only, authenticated by the existing private local-model
service key, and enabled only by the local Compose override. Public origins
disable tutor sessions even if the local flag is accidentally retained. The
native Memory Desk now uses **8772**, avoiding the GGUF service on **8766**.
The generation server retains two CPU threads/one slot and runs below normal
priority; the memory embedding service uses one CPU thread. No new Core or ALE
instance is launched. This serializes the new portal/tutor pipeline; it is not
a claim that all legacy inference entry points have been migrated to one scheduler.

Study improves inspectable evidence and gap tracking, not model weights. Separate
training, independent answer evaluation and isolated code tests are later stages.

This improves evidence gathering and development proposals, not model weights.
The 3B model can still misunderstand tasks or produce invalid plans. Inspect the
actual activity rather than trusting a claim in generated prose. No shell,
package installs, filesystem writes, desktop actions, trading or deployment tools
are available in this portal. Autonomous application of patches requires a future
isolated worktree/test runner, independent checks and rollback workflow.

Native Core already has `llm_tool_loop.py` and `workspace_tools.py`; the public
client portal deliberately does not import their desktop execution authority.
Extending the source catalog or documentation catalog is a reviewed code change.

References checked 2026-10-30:
- https://qwen.readthedocs.io/en/v2.5/framework/function_call.html
- https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md

These document template-dependent function calling. This existing GGUF service
uses explicit JSON planning instead of assuming its template supports native
tool calls. The host remains the authority, regardless of model output.
