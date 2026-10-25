# Testing Niblit desktop

Build target: 25 October 2026. Keep the entire `dist/testing-20261025-commands/niblit`
folder together; the UI-only installer is not the integrated runtime.

## Start

Close the previous Niblit desktop/Core first, then double-click
`Start-Niblit-Testing.cmd` inside the new bundle. This starts local inference
and paper/observe trading. It stores testing memory under
`%LOCALAPPDATA%\Niblit\testing-20261025`, separately from existing memory.
Do not remove that directory between restart tests.

Core uses port 5000, Cloud 8000, and Lean 8100. The launcher checks Core's port
to prevent the new UI from accidentally connecting to the old app. Healthy
existing Cloud/Lean services can be reused. The local model directory remains
external to the bundle; no model weights or API credentials are packaged.
In this checkout, the testing launcher uses the existing Core `.env` when found;
it does not copy it into the bundle. To choose another environment file, set
`NIBLIT_ENV_FILE` to its absolute path before launch. The packaged runtime itself
does not require a source checkout.

## Manual checks

1. **Startup:** wait for the readiness report and desktop window. Confirm the
   core API and Cloud are ready and trading reports paper/observe. Record any
   remaining degraded subsystem rather than treating the window alone as proof
   every subsystem works.
2. **Chat:** ask a short question. Check the response completes and the provider
   identifies an available local model. No remote API key is needed for local
   Cloud inference; optional remote providers may remain disabled.
3. **Continuity:** tell Niblit a distinctive testing fact, ask it about that fact
   in a follow-up, close Niblit normally, and restart with the same launcher.
   Ask again. Distinguish stored chat continuity from explicit knowledge writes:
   a conversational answer is not proof a fact was promoted into KnowledgeDB.
4. **Explicit knowledge:** use `remember test_project: memory-check-20261025`,
   then `recall memory-check-20261025`; repeat recall after a normal restart.
5. **File/code understanding:** ask it to inspect a real file inside the approved
   workspace and explain one function. Check its cited file and explanation
   against the actual code, then ask a follow-up about that same function.
   Set `NIBLIT_WORKSPACE_ROOT` explicitly if testing a folder outside the bundle.
6. **Runtime:** inspect status, memory, and trading pages. Paper/observe mode
   should expose status without live execution. Optional cloud providers,
   exchange connections, and research credentials are separate capabilities.
7. **Shutdown:** close the desktop normally and confirm Core exits. Restart once
   more to check persistence and avoid duplicate processes or port conflicts.

## Report a failure

Include the exact question/action, expected result, actual result, and time.
Attach the relevant part of the console log or the testing `runtime.jsonl`.
Redact credentials and private memory content. Automated build/smoke evidence
is recorded in the build plan and diagnostics, separately from these manual
acceptance checks.

## Interface and connection

Use Settings > Test connection with http://127.0.0.1:5000, then save. Architecture shows actual Core, Cloud, Lean, memory, and event bridge checks. A connected Core alone does not mean every layer is healthy. Each subsystem has refresh, filtering and expandable live details. Settings controls appearance, refresh, model parameters and confirmations.

Commands has Actions and the full original catalogue. Search names or aliases, inspect the actual availability, and prepare the governed action form. Executable means the handler is present and permitted. Operator-only or unavailable commands are listed honestly; selecting a command does not silently send it as chat.

The current Commands build also exposes original desktop operator handlers from
`niblit_router.py`, `niblit_core.py`, `main.py` and the legacy Brain adapter.
Use **Run commands**, search **remember**, enter `test_key: test_value` in the
text argument, Execute and confirm. Then select **recall**, enter `test_value`
as its query and Execute. Other examples are `threads` and `unified status`.
Operator execution does not make a command available to the assistant. Protected
commands retain their permission checks; interactive shell-only commands show
their actual limitation. See `COMMAND_TAB_RESTORATION.md` for validation.

Chat has an explicit choice between **Niblit assistant** and **Model chat**.
Changing the selected model does not change that choice. Clear view clears only
the visible conversation; it does not delete stored memory. Named source-file
questions read the authorized workspace before inference and cite the file.

## Offline testing and current limits

### Paper trading

Open Trading and enable paper trading. This profile uses the packaged Freqtrade
strategy worker on port 8150 and recorded BTC/ETH hourly candles. It is historical
replay, not a live exchange feed. The default simulated account is 10,000 USDT;
the default order stake is 100 USDT. This profile evaluates unleveraged long
entry/exit signals, rather than Freqtrade's full exchange, ROI and intrabar stop
execution engine. Entries reserve cash and charge 0.1% fees;
exits release cash and record net profit or loss. Account, orders and replay
progress persist in the testing data folder's `paper` directory. Paper activation
is remembered across restarts. The launcher refuses an incompatible older
trading service on port 8100 instead of opening against that backend.

Use Create paper entry and Close paper position for manual testing, or choose a
dataset and strategy, then Run recorded candles. Require local AI approval adds
a real local model vote before eligible strategy signals reach runtime risk
checks. Stop after current step preserves the in-flight decision; Pause orders
blocks new submissions. Load replay requires all positions to be closed.

The $100/month net target is an evaluation goal. A working paper ledger or a
historical replay does not establish future profitability. This build does not
connect this operator profile to live exchange order execution.

Local models, canonical memory, conversation storage, workspace browsing and
read-only commands can be tested without remote provider credentials. Model
weights must already exist locally. Web research, remote models, exchanges and
external vector stores need their respective services or network access.

Use the Commands tab's **recall** action for the verified memory retrieval path.
The legacy one-shot command-line option (`-c`) still uses an older router that
can treat a recall command as a general question. This testing release does not
certify every optional AIOS component; inspect Cognitive and Architecture for
actual readiness and failures.
