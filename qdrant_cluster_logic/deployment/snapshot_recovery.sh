#!/usr/bin/env bash
set -euo pipefail
: "${QDRANT_URL:?set QDRANT_URL}"
: "${QDRANT_API_KEY:?set QDRANT_API_KEY}"
: "${QDRANT_COLLECTION:?set QDRANT_COLLECTION}"
echo 'Creating snapshot...'
curl --fail --silent --show-error -X POST "$QDRANT_URL/collections/$QDRANT_COLLECTION/snapshots" -H "api-key: $QDRANT_API_KEY"
echo 'List snapshots:'
curl --fail --silent --show-error "$QDRANT_URL/collections/$QDRANT_COLLECTION/snapshots" -H "api-key: $QDRANT_API_KEY"
echo 'To recover, upload a snapshot file with PUT /collections/$QDRANT_COLLECTION/snapshots/upload?priority=snapshot'
