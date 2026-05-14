#!/usr/bin/env bash
# Idempotent payload index creation.
# HTTP 409 on index creation means the index already exists — treated as SUCCESS.
# Indexes are governance infrastructure and must survive repeated bootstraps.
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
: "${QDRANT_URL:?set QDRANT_URL}"
: "${QDRANT_API_KEY:?set QDRANT_API_KEY}"

ERRORS=0

for spec in "$ROOT_DIR"/collections/*.json; do
  name=$(python3 - <<'PY' "$spec"
import json,sys
print(json.load(open(sys.argv[1]))['collection_name'])
PY
)
  python3 - <<'PY' "$spec" > /tmp/qdrant-index-commands.jsonl
import json,sys
spec=json.load(open(sys.argv[1]))
for field in spec['payload_indexes']:
    print(json.dumps(field))
PY
  while IFS= read -r row; do
    field_name=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['field_name'])" "$row" 2>/dev/null || echo "unknown")
    echo "Ensuring payload index on $name: $field_name"
    status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
      -X PUT "$QDRANT_URL/collections/$name/index" \
      -H "api-key: $QDRANT_API_KEY" \
      -H 'Content-Type: application/json' \
      --data "$row" || echo "000")

    # 2xx = created; 409 = already exists = SUCCESS; others = error
    if [ "$status" = "200" ] || [ "$status" = "201" ] || [ "$status" = "409" ]; then
      if [ "$status" = "409" ]; then
        echo "GOVERNED: index $field_name on $name already exists (HTTP 409). Treating as governed success."
      else
        echo "CREATED:  index $field_name on $name (HTTP $status)"
      fi
    else
      echo "ERROR: index $field_name on $name failed with HTTP $status"
      ERRORS=$((ERRORS + 1))
    fi
  done < /tmp/qdrant-index-commands.jsonl
done

if [ "$ERRORS" -gt 0 ]; then
  echo "Index creation completed with $ERRORS error(s). Review output above."
  exit 1
fi

echo 'Payload indexes ensured from governance blueprints.'
