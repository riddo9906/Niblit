#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
: "${QDRANT_URL:?set QDRANT_URL}"
: "${QDRANT_API_KEY:?set QDRANT_API_KEY}"
for spec in "$ROOT_DIR"/collections/*.json; do
  name=$(python - <<'PY' "$spec"
import json,sys
print(json.load(open(sys.argv[1]))['collection_name'])
PY
)
  python - <<'PY' "$spec" > /tmp/qdrant-index-commands.jsonl
import json,sys
spec=json.load(open(sys.argv[1]))
for field in spec['payload_indexes']:
    print(json.dumps(field))
PY
  while IFS= read -r row; do
    echo "Creating payload index on $name: $row"
    curl --fail --silent --show-error \
      -X PUT "$QDRANT_URL/collections/$name/index" \
      -H "api-key: $QDRANT_API_KEY" \
      -H 'Content-Type: application/json' \
      --data "$row" >/dev/null
  done < /tmp/qdrant-index-commands.jsonl
done
echo 'Payload indexes created from governance blueprints.'
