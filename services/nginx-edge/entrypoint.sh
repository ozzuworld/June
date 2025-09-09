#!/usr/bin/env bash
set -euo pipefail

# Fail early if no upstreams defined
if ! env | grep -q '^UPSTREAM_'; then
  echo "At least one UPSTREAM_* env var is required (e.g. UPSTREAM_IDP, UPSTREAM_ORCH)"
  exit 1
fi

# Expand template -> final config
echo ">>> Rendering nginx.conf with envsubst..."
# envsubst will substitute ${PORT}, ${UPSTREAM_IDP}, ${UPSTREAM_ORCH}, ${UPSTREAM_TTS}, ${UPSTREAM_STT}, etc.
envsubst < /etc/nginx/templates/nginx.conf.template > /etc/nginx/nginx.conf

echo ">>> NGINX configuration:"
cat /etc/nginx/nginx.conf
echo "------------------------------------------"

# Start nginx in foreground
exec nginx -g 'daemon off;'
