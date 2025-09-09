#!/usr/bin/env bash
set -euo pipefail

: "${PORT:=8080}"

# Require IDP so /auth works
if [[ -z "${UPSTREAM_IDP:-}" ]]; then
  echo "UPSTREAM_IDP is required (Keycloak upstream)."
  exit 1
fi

CONF="/etc/nginx/nginx.conf"

# Write full nginx.conf (events + http + server)
# NOTE: we escape NGINX runtime variables like $host as \$host so Bash doesn't expand them.
cat > "$CONF" <<EOF
worker_processes  auto;

events {
  worker_connections  1024;
}

http {
  include       /etc/nginx/mime.types;
  default_type  application/octet-stream;

  sendfile        on;
  tcp_nopush      on;
  keepalive_timeout  65;
  server_tokens off;

  # Trust Cloudflare for real client IP
  real_ip_header CF-Connecting-IP;
  set_real_ip_from 173.245.48.0/20;
  set_real_ip_from 103.21.244.0/22;
  set_real_ip_from 103.22.200.0/22;
  set_real_ip_from 103.31.4.0/22;
  set_real_ip_from 141.101.64.0/18;
  set_real_ip_from 108.162.192.0/18;
  set_real_ip_from 190.93.240.0/20;
  set_real_ip_from 188.114.96.0/20;
  set_real_ip_from 197.234.240.0/22;
  set_real_ip_from 198.41.128.0/17;
  set_real_ip_from 162.158.0.0/15;
  set_real_ip_from 104.16.0.0/13;
  set_real_ip_from 104.24.0.0/14;
  set_real_ip_from 172.64.0.0/13;
  set_real_ip_from 131.0.72.0/22;

  # Default to https if XFP missing (some proxies strip it)
  map \$http_x_forwarded_proto \$resolved_proto {
    default \$http_x_forwarded_proto;
    ""      "https";
  }

  server {
    listen      ${PORT};
    server_name allsafe.world;

    # Health check
    location = /healthz { return 200; }

    # ---- Keycloak (IDP) ----
    location /auth/ {
      proxy_pass         ${UPSTREAM_IDP};
      proxy_http_version 1.1;

      # Preserve host/proto so Keycloak builds correct URLs
      proxy_set_header   Host \$host;
      proxy_set_header   X-Forwarded-Proto \$resolved_proto;

      # Client IP chain (Cloudflare sends CF-Connecting-IP)
      proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;

      proxy_set_header   Connection "";
      proxy_read_timeout 120s;
      client_max_body_size 20m;
    }
EOF

# Conditionally add other services if env set
if [[ -n "${UPSTREAM_ORCH:-}" ]]; then
cat >> "$CONF" <<'EOF'
    # ---- Orchestrator ----
    location /orchestrator/ {
      proxy_pass         ${UPSTREAM_ORCH};
      proxy_http_version 1.1;
      proxy_set_header   Host $host;
      proxy_set_header   X-Forwarded-Proto $resolved_proto;
      proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header   Connection "";
    }
EOF
fi

if [[ -n "${UPSTREAM_TTS:-}" ]]; then
cat >> "$CONF" <<'EOF'
    # ---- Text-to-Speech ----
    location /tts/ {
      proxy_pass         ${UPSTREAM_TTS};
      proxy_http_version 1.1;
      proxy_set_header   Host $host;
      proxy_set_header   X-Forwarded-Proto $resolved_proto;
      proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header   Connection "";
    }
EOF
fi

if [[ -n "${UPSTREAM_STT:-}" ]]; then
cat >> "$CONF" <<'EOF'
    # ---- Speech-to-Text ----
    location /stt/ {
      proxy_pass         ${UPSTREAM_STT};
      proxy_http_version 1.1;
      proxy_set_header   Host $host;
      proxy_set_header   X-Forwarded-Proto $resolved_proto;
      proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header   Connection "";
    }
EOF
fi

# Close blocks
cat >> "$CONF" <<'EOF'
  } # server
} # http
EOF

echo ">>> Final /etc/nginx/nginx.conf"
cat "$CONF"
echo "------------------------------------------"

# Validate and start
nginx -t
exec nginx -g 'daemon off;'
