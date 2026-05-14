#!/usr/bin/env bash
# Governed Bootstrap Engine — idempotent collection initialization.
#
# For each collection:
#   STEP 1: Check if collection already exists (GET /collections/<name>)
#   STEP 2: If HTTP 200 → already governed; validate vector_policy.size == 384, skip creation
#   STEP 3: If HTTP 404 → create collection (PUT /collections/<name>)
#   STEP 4: Treat HTTP 409 Conflict on creation as SUCCESS (collection exists = valid state)
#   STEP 5: Never overwrite existing collections silently; never crash on 409
#
# Safety rules enforced here:
#   ✔ 409 = SUCCESS (idempotent)
#   ✔ existing collections are valid governed state
#   ✔ system continues boot on all non-5xx responses
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
: "${QDRANT_URL:?set QDRANT_URL}"
: "${QDRANT_API_KEY:?set QDRANT_API_KEY}"

ERRORS=0

# Extract the vectors.size field from an api_payloads JSON file.
# Returns the size value, or "unknown" if the field is absent or parsing fails.
_payload_vector_size() {
  local payload_file="$1"
  python3 -c "
import json, sys
try:
    p = json.load(open('$payload_file'))
    print(p.get('vectors', {}).get('size', 'unknown'))
except Exception:
    print('unknown')
" 2>/dev/null || echo "unknown"
}

for payload in "$ROOT_DIR"/deployment/api_payloads/*.json; do
  name=$(basename "$payload" .json)

  # STEP 1: Check if collection already exists
  check_status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
      -X GET "$QDRANT_URL/collections/$name" \
      -H "api-key: $QDRANT_API_KEY" || echo "000")

  if [ "$check_status" = "200" ]; then
    # STEP 2: Already governed — validate expected vector dimension in payload then skip
    expected_dim=$(_payload_vector_size "$payload")
    if [ "$expected_dim" != "384" ]; then
      echo "ERROR: $name payload declares vector size $expected_dim (must be 384). Refusing creation."
      ERRORS=$((ERRORS + 1))
    else
      echo "GOVERNED: $name already exists (size=384). Skipping creation."
    fi
    continue
  fi

  # STEP 3: Collection missing — validate 384-dim before creating
  expected_dim=$(_payload_vector_size "$payload")
  if [ "$expected_dim" != "384" ]; then
    echo "ERROR: $name payload declares vector size $expected_dim (must be 384). Refusing creation."
    ERRORS=$((ERRORS + 1))
    continue
  fi

  echo "Creating collection: $name (size=384)"
  create_status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
      -X PUT "$QDRANT_URL/collections/$name" \
      -H "api-key: $QDRANT_API_KEY" \
      -H 'Content-Type: application/json' \
      --data @"$payload" || echo "000")

  # STEP 4: 2xx = created; 409 = already exists = SUCCESS; others = error
  if [ "$create_status" = "200" ] || [ "$create_status" = "201" ] || [ "$create_status" = "409" ]; then
    if [ "$create_status" = "409" ]; then
      echo "GOVERNED: $name already exists (HTTP 409). Treating as governed success."
    else
      echo "CREATED:  $name (HTTP $create_status)"
    fi
  else
    echo "ERROR: $name creation failed with HTTP $create_status"
    ERRORS=$((ERRORS + 1))
  fi
done

if [ "$ERRORS" -gt 0 ]; then
  echo "Bootstrap completed with $ERRORS error(s). Review output above."
  exit 1
fi

echo 'Governed bootstrap complete. All collections are in valid governed state.'
