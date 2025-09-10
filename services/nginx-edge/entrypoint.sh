#!/usr/bin/env bash
set -euo pipefail

: "${PORT:=8080}"

# Require IDP so /auth works
if [[ -z "${UPSTREAM_IDP:-}" ]]; then
  echo "UPSTREAM_IDP is required (Keycloak upstream)."
  exit 1
fi

# Normalize upstreams to ensure a single trailing slash in proxy_pass
IDP_UPSTREAM="${UPSTREAM_IDP%/}"
ORCH_UPSTREAM="${UPSTREAM_ORCH:-}"
TTS_UPSTREAM="${UPSTREAM_TTS:-}"
STT_UPSTREAM="${UPSTREAM_STT:-}"
[[ -n "$ORCH_UPSTREAM" ]] && ORCH_UPSTREAM="${ORCH_UPSTREAM%/}"
[[ -n "$TTS_UPSTREAM"  ]] && TTS_UPSTREAM="${TTS_UPSTREAM%/}"
[[ -n "$STT_UPSTREAM"  ]] && STT_UPSTREAM="${STT_UPSTREAM%/}"

CONF="/etc/nginx/nginx.conf"

# Write full nginx.conf (events + http + server)
# NOTE: We escape NGINX runtime variables like $host as \$host so Bash doesn't expand them.
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

  # Trust Cloudflare for real client IP (IPv4 ranges)
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
      proxy_pass         ${IDP_UPSTREAM}/;  # ensure trailing slash behavior
      proxy_http_version 1.1;

      # Use upstream host for Cloud Run routing (fixes 502)
      proxy_set_header   Host \$proxy_host;
      proxy_ssl_server_name on;

      # Forward external context so Keycloak builds correct URLs
      proxy_set_header   X-Forwarded-Proto \$resolved_proto;
      proxy_set_header   X-Forwarded-Host  \$host;
      proxy_set_header   X-Forwarded-Port  \$server_port;
      proxy_set_header   X-Forwarded-Prefix /auth;

      # Client IP chain (Cloudflare sends CF-Connecting-IP)
      proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;

      proxy_set_header   Connection "";
      proxy_read_timeout 120s;
      client_max_body_size 20m;
    }
EOF

# Conditionally add other services if env set (unquoted heredocs so env expands;
# we escape NGINX vars with backslashes)
if [[ -n "${ORCH_UPSTREAM}" ]]; then
cat >> "$CONF" <<EOF
    # ---- Orchestrator ----
    location /orchestrator/ {
      proxy_pass         ${ORCH_UPSTREAM}/;
      proxy_http_version 1.1;
      proxy_set_header   Host \$proxy_host;
      proxy_ssl_server_name on;
      proxy_set_header   X-Forwarded-Proto \$resolved_proto;
      proxy_set_header   X-Forwarded-Host  \$host;
      proxy_set_header   X-Forwarded-Port  \$server_port;
      proxy_set_header   X-Forwarded-Prefix /orchestrator;
      proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
      proxy_set_header   Connection "";
    }
EOF
fi

if [[ -n "${TTS_UPSTREAM}" ]]; then
cat >> "$CONF" <<EOF
    # ---- Text-to-Speech ----
    location /tts/ {
      proxy_pass         ${TTS_UPSTREAM}/;
      proxy_http_version 1.1;
      proxy_set_header   Host \$proxy_host;
      proxy_ssl_server_name on;
      proxy_set_header   X-Forwarded-Proto \$resolved_proto;
      proxy_set_header   X-Forwarded-Host  \$host;
      proxy_set_header   X-Forwarded-Port  \$server_port;
      proxy_set_header   X-Forwarded-Prefix /tts;
      proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
      proxy_set_header   Connection "";
    }
EOF
fi

if [[ -n "${STT_UPSTREAM}" ]]; then
cat >> "$CONF" <<EOF
    # ---- Speech-to-Text ----
    location /stt/ {
      proxy_pass         ${STT_UPSTREAM}/;
      proxy_http_version 1.1;
      proxy_set_header   Host \$proxy_host;
      proxy_ssl_server_name on;
      proxy_set_header   X-Forwarded-Proto \$resolved_proto;
      proxy_set_header   X-Forwarded-Host  \$host;
      proxy_set_header   X-Forwarded-Port  \$server_port;
      proxy_set_header   X-Forwarded-Prefix /stt;
      proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
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
