# Qdrant Cloud copy/paste commands

Qdrant Cloud uses the same collection API payloads as self-hosted Qdrant. In this folder:

- `collections/*.json` are governance blueprints with extra operator metadata
- `deployment/api_payloads/*.json` are the exact JSON payloads to paste into the Qdrant Cloud UI/API when creating collections

## Create a collection from a UI/API-ready payload

```bash
curl -X PUT "$QDRANT_URL/collections/semantic_memory" \
  -H "api-key: $QDRANT_API_KEY" \
  -H 'Content-Type: application/json' \
  --data @qdrant_cluster_logic/deployment/api_payloads/semantic_memory.json
```

## Create payload indexes

```bash
curl -X PUT "$QDRANT_URL/collections/semantic_memory/index" \
  -H "api-key: $QDRANT_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"field_name":"trace_id","field_schema":"keyword"}'
```

```bash
curl -X PUT "$QDRANT_URL/collections/semantic_memory/index" \
  -H "api-key: $QDRANT_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"field_name":"telemetry.epoch_id","field_schema":{"type":"integer","lookup":false,"range":true}}'
```

## Validate collection status

```bash
curl "$QDRANT_URL/collections/semantic_memory" -H "api-key: $QDRANT_API_KEY"
```

## Notes for the Qdrant Cloud UI

- In **Collections → Create collection**, paste the matching file from `deployment/api_payloads/`.
- In **Collection → Payload indexes**, add the indexes listed in `collections/<name>.json`.
- Keep `strict_mode_config.enabled=true` so non-indexed filtering is blocked in line with governed retrieval expectations.
