# Niblit Steward and live environment tools

Steward is a separate OpenAI API agent, with its own instructions and sessions. It does not inherit this Codex chat, memory or desktop access. The saved definition uses `gpt-6-astra`; Niblit's existing `OPENAI_MODEL` setting is preserved. Override the saved-agent model with `OPENAI_AGENT_MODEL` before exporting/registering.

`agent.json` is the Agents API definition. `function.json` is a strict reusable function definition; `chat-function.json` wraps the same contract for Chat Completions. The Agents API does not accept the Responses-specific `strict` field, so `agent.json` omits it. Runtime validation remains strict, including nested fields.

The Python implementation is `modules/environment_navigator.py`, registered on the same governed Core tool loop as existing research/workspace tools. It performs bounded public-page reads or policy-checked workspace reads/listings. It never clicks a browser, operates a native app, runs commands, submits forms or trades. Application/virtual-world requests explicitly report unsupported. Website URLs containing credentials, queries or fragments are rejected. Private-network requests and unsafe redirects are blocked by the governed fetch policy. Workspace file reads use `object_id: "file"`; other workspace observations list one directory. Context is descriptive data, not executable instructions.

Open **Commands → Live tool workspace** in the new desktop release:

- Inspect a target and watch purpose, requested target, actions, evidence, errors and timestamps.
- Send guidance while an observation runs or afterwards. Guidance is recorded; it does not execute commands.
- Stop at an action boundary. An in-flight read may complete before stop takes effect.
- Ask Steward to review the run. This explicit button uses the updated Responses adapter with the configured `OPENAI_MODEL`, Steward's review persona, an operational summary and operator guidance. It does not run the saved Managed Agent session. Full page/file contents stay local. Failures appear in the ledger.
- To connect the saved Managed Agent, start a session for its saved ID in OpenAI, then enter that session ID under **Connect a saved OpenAI agent session**. Handling pending calls retrieves actual `required_actions`, validates the entire batch, runs only this named tool (at most two calls), and returns the matching call/turn IDs through the Agents API. All observations use Core's shared ledger. Results contain operational proof and guidance; full file/page contents stay local. Returning results permits paid inference to continue. There is no automatic session polling or background inference.

Local endpoints:

- `GET /api/tools/runs`: last 40 runs, held in Core process memory until restart.
- `POST /api/tools/runs`: the exact navigator argument object.
- `POST /api/tools/runs/{id}/control`: `{ "action": "guidance", "message": "..." }` or `{ "action": "stop" }`.
- `POST /api/tools/runs/{id}/review`: explicit Responses review.
- `POST /api/steward/sessions/{session_id}/handle-pending`: explicit Managed Agent function bridge.

The view polls every 1.5 seconds. It exposes operational actions and results, not private model reasoning. There is no continuous desktop screen feed, automatic self-training, automatic trading or guaranteed commercial outcome. Desktop observation/control requires a future host adapter and an explicit visible capture scope.

Registration status is recorded in `registration.json`. A saved agent is not proof of usable inference credits or a completed session. The initial Responses connectivity test returned HTTP 429. A subsequent saved-agent test turn failed with `usage_limit_exceeded`; further paid tests are pending confirmation of credits. No credit purchase was made.

The source `.env` now selects `OPENAI_MODEL=gpt-6-astra`. GPT-6 Responses use low reasoning effort by default (`OPENAI_REASONING_EFFORT` can override it). Ordinary conversation permits up to 2,048 output tokens including reasoning; review permits 1,000. These are per-request token bounds, not an account-wide dollar cap. API-key charges are separate from the user's Codex/ChatGPT subscription. Use local models for routine work and request API reviews deliberately.

Use `Start-Niblit-Connected.cmd` from the Niblit checkout to launch the connected release with the checkout's explicit `.env`. When no custom memory paths are configured, this launcher reuses existing memory/chat/knowledge databases in `dist/niblit`. It leaves the older binaries available. Avoid running two releases against those same stores simultaneously. Disposable verification bypasses this launcher and supplies isolated state with API credentials disabled.

Official contracts: [Agents configuration](https://developers.openai.com/api/docs/guides/agents-api/configuration), [function tool results](https://developers.openai.com/api/docs/guides/agents-api/tools/functions).
