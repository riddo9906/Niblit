# Niblit local GGUF activation — 2026-11-20

## Verified state
- `D:\Models` contains four actual GGUF files:
  - Qwen2.5-Coder-14B-Instruct Q4_K_M (~8.37 GiB)
  - Qwen2.5-Coder-3B-Instruct Q4_K_M (~1.96 GiB)
  - Llama 3.2 1B Instruct Q4_K_M (~0.75 GiB)
  - Qwen2.5 0.5B Instruct Q4_K_M (~0.46 GiB)
- The pre-existing `llama-server.exe` on port **8966** still serves `qwen2.5-coder-3b` from its known-good **C:** profile. No change was made to this process.
- New Qwen2.5-Coder **14B** `llama-server.exe` on `127.0.0.1:8967`, model `D:\Models\qwen2.5-coder-14b-instruct-q4_k_m.gguf`, context 2048, 4 CPU threads, zero GPU layers, parallel 1, using the existing API key file without exporting its value. The server loaded the GGUF, finished warm-up and returned HTTP 200 from `/health`. It used ~8.45 GiB process working set.
- Niblit Core `127.0.0.1:5200/market-desk/` and Niblit Cloud `127.0.0.1:8201/health` remained HTTP 200. The original r7 trading runtime remained active; no MT5/Freqtrade execution settings or sessions were changed by inference setup.
- The four-model inventory is recorded at `D:\NiblitAIOS\config\trading-software-20261115\local-gguf-model-pool.json`. This is inventory only; it is not a replacement for Niblit's running model manager.
- Updated cloud server source registry `C:\Users\Riyaad\Documents\GitHub\niblit-cloud-server\app\local_models.py` to detect the 14B canonical ID `qwen2.5-coder-14b`, metadata, 2048 context and role alias `large-coder` when `D:\Models` is selected as the GGUF directory. Tested catalog discovery/model identity: **13 passed**, no failures.
- Idempotent launch script: `C:\Users\Riyaad\Documents\GitHub\Niblit\scripts\Start-Niblit-14B.ps1`. PowerShell parse check returned zero errors. Running it with the server already healthy reported no duplicate started.

## Reopen 14B later
```powershell
& "C:\Users\Riyaad\Documents\GitHub\Niblit\scripts\Start-Niblit-14B.ps1"
Invoke-RestMethod http://127.0.0.1:8967/health
```

## Unfinished integration
- The current 14B sidecar **does not automatically register** with the already running Niblit Cloud instance on port 8201 or replace the default model in Niblit Chat/Tauri UI. It can be used by a client that points to its authenticated local OpenAI-compatible interface on `http://127.0.0.1:8967/v1`; preserve the API key file mechanism.
- **Chat completion through the new 14B API has not yet been verified**. Health 200 demonstrates model loading and server readiness, not correctness of generated replies.
- The D: drive copies of the existing three GGUFs were discovered, but the running 3B model process continues using the known-good C: copy and the existing Cloud may still discover its original C: model directory.
- Next coding task: add a model-aware route in Niblit Cloud and frontend that directs the `qwen2.5-coder-14b` model ID to the already-loaded local 8967 sidecar, keeps 3B as default/backup on 8966, advertises only healthy model endpoints, and validates 14B prompt/reply with actual inference. Avoid eagerly double-loading the 8.37 GiB 14B model into another process.
- Then build/deploy Niblit's Cloud/UI changes in a versioned release while preserving current active demo trading sessions and their persistent broker positions.

## Built-in llama.cpp UI finding
- The 14B API remains healthy. Enabling llama-server's `--ui` option on the installed executable did **not** produce a browser interface: GET `/`, `/index.html`, `/ui`, `/chat` and `/webui` returned 404. This does not affect the model's loaded/healthy API, but **do not claim a browser frontend is installed**. The persistent launch script therefore retains the minimal API-only configuration for future starts. The currently running instance may still carry the inert `--ui` flag until its next restart.
