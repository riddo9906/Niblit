# Connected desktop release — 2026-10-28

Launch from the checkout with `Start-Niblit-Connected.cmd`. The complete release lives in `dist/latest-20261028-connected/niblit`; keep that folder together. The launcher loads the checkout's `.env` explicitly and reuses the previous `dist/niblit` memory/chat/knowledge stores when no custom paths are configured. Do not run both releases against the same stores simultaneously.

## What changed

- Desktop natural conversation now uses the selected model through the bound Core API. Exact Core commands retain their existing governed dispatch. Failed inference produces an explicit error instead of a misleading knowledge-recall reply.
- Core advertises the configured OpenAI model as configured, not connectivity-verified. `OPENAI_MODEL=gpt-6-astra` is preserved. The adapter now uses Responses by default, retains an explicit legacy mode, normalizes actual model output, omits unsupported temperature settings for GPT-6, bounds retries and never executes model tool calls implicitly. Low reasoning effort is the default for GPT-6.
- Runtime WebSocket snapshots run off the API event loop. UI observations no longer feed hypothesis learning, capability lifecycle events, model-selection persistence or market knowledge flushing back into the runtime. Actual boot/command events retain their existing audit path.
- `lifecycle_engine.py` uses `inspect.iscoroutinefunction`. The current search implementation prefers `ddgs`, and the optional package dependency now matches that name.
- Commands includes the live environment tool view: purpose, target, actions, evidence, timing, failures, guidance, cooperative stop and explicit API review. See `agents/niblit-steward/README.md` for the executable contract, exports and external-agent bridge.

## Evidence and limits

Native report: `diagnostics/connected-native-final-20261028/verification.json`.

The isolated native acceptance passed automatic Core/Cloud/Lean boot, 80 Cloud catalogue reads, three real local model streams, live runtime telemetry, Core command response with native-origin CORS, selected-model conversation, the shared live tool ledger and disabled execution. Health requests with telemetry active averaged 8.5 ms (maximum 117.4 ms). The first cold Core help command took 64.4 seconds; subsequent manual help/status checks in the preceding run took roughly 12–14 seconds. Cold command latency remains a limitation; the lightweight liveness probe is not a claim that every command is fast.

The user independently tested `hi` in the native connected release and received a real conversational reply. Browser UI verification also ran an actual workspace observation and recorded operator guidance in the shared ledger. Frontend connection/chat/streaming/preferences checks passed (17 tests); Signal Desk/Pip checks passed (12 tests). The focused backend suite passed 76 tests before the additional exact-model catalogue check, which also passed.

Steward was registered successfully as a separate saved OpenAI agent with its environment function. Its initial inference turn failed with `usage_limit_exceeded`; no successful OpenAI inference or live external tool round trip is claimed. Further paid testing awaits the user's confirmation of credits. Local/mock checks do not consume those credits. The saved agent does not inherit the current Codex chat or desktop access.

The first environment adapters inspect permitted workspace files/directories and public pages. There is no native desktop-control adapter or continuous screen feed yet. Ruflo is not connected to an actual bridge endpoint. This release does not establish authenticated live trading/order execution or validate every existing command; acceptance used observe/paper/replay and disabled financial execution.
