#!/usr/bin/env bash
set -euo pipefail

: "${PORT:=8080}"

# Require IDP so /auth works
if [[ -z "${UPSTREAM_IDP:-}" ]]; then
  echo "UPSTREAM_IDP is required (Keycloak upstream)."
  exit 1
fi

CONF="/etc/nginx/nginx.conf"

cat > "$CONF" <<EOF
server {
  listen       ${PORT};
  server_name  allsafe.world;

  # Health check
  location = /healthz { return 200; }
EOF

# Always add /auth
cat >> "$CONF" <<'EOF'
  # ---- Keycloak (IDP) ----
  location /auth/ {
    proxy_pass        ${UPSTREAM_IDP};
    proxy_http_version 1.1;
    proxy_set_header  Host $host;
    proxy_set_header  X-Forwarded-Proto https;
    proxy_set_header  X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header  Connection "";
    proxy_read_timeout 120s;
    client_max_body_size 20m;
  }
EOF

# Conditionally add other services if env set
if [[ -n "${UPSTREAM_ORCH:-}" ]]; then
cat >> "$CONF" <<'EOF'
  # ---- Orchestrator ----
  location /orchestrator/ {
    proxy_pass        ${UPSTREAM_ORCH};
    proxy_http_version 1.1;
    proxy_set_header  Host $host;
    proxy_set_header  X-Forwarded-Proto https;
    proxy_set_header  X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header  Connection "";
  }
EOF
fi

if [[ -n "${UPSTREAM_TTS:-}" ]]; then
cat >> "$CONF" <<'EOF'
  # ---- Text-to-Speech ----
  location /tts/ {
    proxy_pass        ${UPSTREAM_TTS};
    proxy_http_version 1.1;
    proxy_set_header  Host $host;
    proxy_set_header  X-Forwarded-Proto https;
    proxy_set_header  X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header  Connection "";
  }
EOF
fi

if [[ -n "${UPSTREAM_STT:-}" ]]; then
cat >> "$CONF" <<'EOF'
  # ---- Speech-to-Text ----
  location /stt/ {
    proxy_pass        ${UPSTREAM_STT};
    proxy_http_version 1.1;
    proxy_set_header  Host $host;
    proxy_set_header  X-Forwarded-Proto https;
    proxy_set_header  X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header  Connection "";
  }
EOF
fi

# Close server
echo "}" >> "$CONF"

echo ">>> Final /etc/nginx/nginx.conf"
cat "$CONF"
echo "------------------------------------------"

# Validate and start
nginx -t
exec nginx -g 'daemon off;'
