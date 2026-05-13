#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
: "${QDRANT_URL:?set QDRANT_URL}"
: "${QDRANT_API_KEY:?set QDRANT_API_KEY}"
for payload in "$ROOT_DIR"/deployment/api_payloads/*.json; do
  name=$(basename "$payload" .json)
  echo "Creating collection: $name"
  curl --fail --silent --show-error \
      -X PUT "$QDRANT_URL/collections/$name" \
      -H "api-key: $QDRANT_API_KEY" \
      -H 'Content-Type: application/json' \
      --data @"$payload" >/dev/null
done
echo 'Collections initialized from deployment/api_payloads.'
