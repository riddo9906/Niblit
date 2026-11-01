# Cloud local-AI bridge audit — 31 October 2026

Read-only source inspection; no provider activated, model downloaded, private
environment changed or inference request sent.

## Existing partial implementation

- Cloud `app/config.py`: OLLAMA_BASE_URL, default http://localhost:11434.
- `app/model_registry.py`: actual Ollama model discovery using GET /api/tags.
  A downloaded model can be discovered when the correct Ollama endpoint is set.
- `app/providers/ollama_provider.py`: POST /api/chat, model/messages and bounded
  output option; embeddings remain a stub. Health/start currently report ready
  without checking the server. Temperature is placed at top level rather than
  alongside num_predict in options; validate against the chosen server contract.
- `app/providers/registry.py`: registers Ollama only when OLLAMA_BASE_URL is
  explicitly present. This differs from model discovery's default URL behavior.
- `app/providers/llamacpp_provider.py`: LLAMA_CPP_SERVER_URL and /completion;
  currently defaults to port11434 (same as Ollama), so explicit configuration
  is needed to avoid a protocol/endpoint mismatch.
- `app/providers/remote_provider.py`: generic OpenAI-compatible HTTP adapter,
  potentially reusable after protocol/auth validation for Docker Model Runner.
- `app/runtime.py`: initializes the separate provider/model registries.

## The integration gap

The primary Cloud /v1/chat/completions route takes app.state.model_manager and
routes through ModelManager. Its chat method constructs GGUFEngine, which loads
llama-cpp-python from an on-disk GGUF. The separate registry is exposed on app
state, but this inspected primary path does not dispatch to OllamaProvider.
Downloaded/discovered models therefore are not proof that desktop chat uses them.
Cloud app/local_models.py also explicitly describes local GGUF discovery with
no Ollama substitution.

No Docker Model Runner port12434-specific configuration was found in the searched
Cloud app sources. Docker's Ollama compatibility could make the existing adapter
reusable, but endpoint prefix, model IDs, options, authentication and runtime
capabilities need an actual contract check before enabling it.

## Next bounded implementation

1. Choose one explicit backend and exact discovered model; no paid fallback.
2. Implement real health/model identity and consistent discovery/registration.
3. Route both model listing and primary chat through that same selected backend,
   preserving existing response/tool/stream/error contracts.
4. Keep one upstream task owner across Core/Cloud/HTTP inference, rather than
   acquiring conflicting nested reservations or loading another GGUF worker.
5. Mock unavailable/model-missing/options/stream/timeout cases; then make one
   authorized local-only end-to-end request with the selected Docker model.
6. Only then update the desktop profile and dated frozen release acceptance.

This confirms the owner's recollection of an existing partial bridge. It should
be completed by reusing those adapters, not creating another model framework.
