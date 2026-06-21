# Multi-repository architecture alignment

## Repository roles

- Niblit: cognitive core for governance, memory, reasoning, learning, planning, and decision approval.
- Niblit-cloud-server: AI inference and communication layer for prompt construction, model routing, caching, capability detection, and OpenAI-compatible APIs.
- niblit-lean-algos: market execution layer for broker connectivity, market data, portfolio management, order routing, and execution telemetry.

## Responsibility boundaries

1. Market events enter the execution layer.
2. The execution layer emits normalized execution events.
3. The cloud server exposes inference services without trading logic.
4. The cognitive core consumes those services, evaluates policies, and approves or rejects decisions.
5. Approved decisions flow back to the execution layer.

## Shared event contract

The shared event names are defined in core/messages.py and are intended to be used as the canonical event vocabulary across all repositories.
