#!/usr/bin/env bash
set -euo pipefail

: "${PORT:?PORT env var required}"
: "${UPSTREAM_URL:?UPSTREAM_URL env var required (e.g., https://<keycloak>.run.app)}"

# Render nginx.conf from template using envsubst
envsubst '${PORT} ${UPSTREAM_URL}' \
  < /etc/nginx/templates/nginx.conf.template \
  > /etc/nginx/nginx.conf

# Show effective config for debugging
echo "----- Rendered /etc/nginx/nginx.conf -----"
cat /etc/nginx/nginx.conf
echo "------------------------------------------"

# Smoke check
nginx -t

# Start nginx in the foreground
exec nginx -g 'daemon off;'
