# Multi-step research and recovery implementation checkpoint

Recorded 2026-11-01T19:49:34.476202+00:00. Integrated into existing repositories; patches already applied. No duplicate installation or competing task/memory authority.

## IMPLEMENTED

Core root: C:\Users\Operator\Documents\GitHub\Niblit; HEAD1b40c4113b0df61ecb561b73b8f7a38ed4280832.
Cloud root: C:\Users\Operator\Documents\GitHub\Niblit-cloud-server; HEADc6f2291f0ca9fc76ab77b3f2723d439c7dd78c32.
All prior dirty/untracked work preserved; baseline status/diffs/preimages in task work/research-recovery.

Core modules/llm_tool_loop.py now forwards its held lease to Cloud across model/tool/model steps, respects requested generation budgets, exposes optional selection from existing tool registrations, applies required selection only to the initial turn, advertises the existing zero-argument runtime-status contract precisely, cooperatively stops future work after cancellation, and propagates forced-final outages rather than returning silent empty success. No tool catalog or permission gate removed.
Core modules/task_admission.py carries cancellation through nested synchronous task contexts, classifies asyncio cancellation conservatively, distinguishes definite HTTP rejections from ambiguous transport failures, and refuses to acknowledge success when delegated work remains quarantined.
Core server.py dispatches governed research in a worker, observes client disconnect/coroutine cancellation, stops further steps after active generation drains, reports busy/uncertain outcomes, and supports backward-compatible tool_names/initial tool_choice narrowing through existing registrations. Default tool catalog remains intact; every call still passes host schema/authorization checks.
Cloud app/main.py includes tool-schema costs in context budgeting and reuses its existing GGUF text-tool normalization from one shared helper. Cloud app/shared_gguf.py now uses that same normalizer; this restores the embedded engine's existing registered-tool protocol in shared inference. Definite model4xx rejections complete a failed child without poisoning unrelated work; unknown delivery stays quarantined with no retry/fallback.
Core local_brain.py/niblit_brain.py/native-cloud profile align270/300sec outer waits with bounded240sec generation; explicit caller timeout overrides remain supported. Existing start-portal-local-model.ps1 has bounded context parameter(default8192); Cloud shared profile matches8192. Same model/weights, one slot, two CPU threads, no download or second model. Private env/permissions and OPENAI_MODEL unchanged.
Tests: Core tests/test_research_recovery.py; Cloud tests/test_shared_gguf.py.

## VERIFIED

Final Core:70 tests passed. Final Cloud:247 tests passed;1 previously reproduced unrelated Windows/Termux test explicitly excluded. Fixtures cover multi-step ownership, unknown tools, outages, definite rejection, premature/uncertain completion, cancellation during worker execution, actual Core-handler cancellation/error codes, and existing guarded recovery refusing active producers/busy models while preserving source evidence. Controlled doubles are not real broker proof.

Actual Core HTTP /v1/inference/chat with enable_tools=true, tool_names=[runtime_status], initial tool_choice=required and128-token generation budget executed runtime_status successfully through the original Core executor and returned a final model answer. Real Cloud and existing local Qwen were used; no scripted model response. Separate SQLite observation confirmed one core_tool_loop parent with exactly2 completed child generations, then release. Native generated prose/citations are not proof of every subsystem assertion; the executed trace and durable ownership are the acceptance evidence.

Actual client-disconnect test observed one delegated child active, cancelled the client request, confirmed the parent stayed reserved, allowed that generation to finish, and observed exactly1 completed child with no further inference before parent release. The model was not forcibly killed for this test. Earlier busy/diagnostic-timeout attempts are retained separately and not counted as cancellation success.

Real failure reconciliation: earlier90sec model timeout produced safe quarantine. Another actual request failed because4503 tokens exceeded4096 context. That failure and a later unexecuted JSON-text answer were preserved, not called tool success. Restored actual behavior by expanding the same idle model to8192, counting tool schemas, and restoring the existing tool normalizer. Existing owner-only recovery was used only after producers were stopped and model idle. A Windows background-launch pipe stall and a changed-PID guard refusal required completing restoration against verified listener children; no arbitrary process termination or automatic quarantine reset. Model process now21096, one process. Activation/recovery evidence is retained.

Final state: SQLite integrity ok; Core5000, Cloud8000, memory8772, desk8767, Lean8100 and portal8769 HTTP200. Authority idle at final snapshot. Freqtrade dry_run=true/state=stopped,3 existing positions unchanged; Lean observe/execution disabled. No orders, previews, consent-token requests, paid generation or execution permission changes.

## BLOCKED / NOT YET IMPLEMENTED

Legacy remote Qdrant connectivity remains separate from working canonical local memory; do not silently redirect it. Existing research search provider reported its monthly SerpAPI quota exhausted; no quota bypass/paid expansion attempted. Full native3B research accuracy/all tools/all cancellation combinations are not certified by one status request; model prose remains unverified. Inference admission HTTP calls can still time out under load and fail closed; they must not be blindly retried after ambiguous acquisition. Earlier live model-status diagnostic timed out; durable child observation was used for the successful disconnect check.
Actual authorized non-live order lifecycle still requires current human-reviewed tickets, account/risk checks and position reconciliation. Engine stopped and3/3 existing slots occupied. Never close positions or arm entries to make a test pass. No live trading enabled.

## CONTEXT MAP / RECOVERY

Sole living map: C:\Users\Operator\Documents\GitHub\Niblit\docs\agent-context\NIBLIT_CONTEXT_MAP.md.
Detailed hashes/evidence: research-recovery-checkpoint.json and evidence/research-recovery/.
Preimages, baseline diffs and guarded service-activation helpers: C:\Users\Operator\Documents\Codex\2026-11-01\referenced-chatgpt-conversation-this-is-an\work\research-recovery. Review later changes before reversing individual hunks. Never reset/clean/stash or drop canonical ledgers. Existing original task_delegations journal remains the authority; no new ledger was introduced.
For startup, use existing source/venvs, native-cloud.env.example and Cloud .env.shared-gguf.example, existing memory8772 and original authenticated model8766. Original model launcher now accepts -ContextSize8192. Invoke the PowerShell background launcher directly; avoid waiting on inherited background output pipes with subprocess.run(capture_output=True). Verify listeners/process identity rather than reusing stale parent PIDs. Do not forcibly stop a busy generation or clear ownership on a timer. Existing scripts/runtime-task-status.py --recover --confirm-producers-stopped remains owner-only and checks all known producer ports/model idleness.

## NEXT ACTION / COPY-PASTE CONTINUATION

Continue in the existing roots. Read the canonical map, this checkpoint and source hashes; inspect actual HEAD/status/diffs and preserve all changes. Verify read-only monitoring and outcome reconciliation for the3 existing dry-run positions using current observations and existing adapters/ledgers; distinguish cached engine state, public mark-to-market estimates and verified broker outcomes. Reuse original execution gateway/strategy/memory authorities. Prepare the original human-reviewed lifecycle workflow only when current account/risk/position state permits; no order, position close, engine-entry start, approval grant or ambiguous retry without required current authorization. Keep shared research cancellation/ownership working and update this same context map with evidence before interruption.
