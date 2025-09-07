#!/usr/bin/env sh
set -euo pipefail
STAMP="$(date -u +%F-%H%M)"
FILE="/tmp/db-${STAMP}.sql.gz"
pg_dump "$NEON_DB_URL" | gzip > "$FILE"
aws --endpoint-url "${R2_ENDPOINT}" s3 cp "$FILE" "s3://${R2_BUCKET}/postgres/$(basename "$FILE")"
