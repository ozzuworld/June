#!/usr/bin/env bash
# services/nginx-edge/entrypoint.sh
# Improved version with better debugging and error handling

set -euo pipefail

: "${PORT:=8080}"

echo "🚀 Nginx-edge starting..."
echo "📋 Environment check:"
echo "   PORT: $PORT"
echo "   UPSTREAM_IDP: ${UPSTREAM_IDP:-❌ NOT_SET}"
echo "   UPSTREAM_ORCH: ${UPSTREAM_ORCH:-⚠️  NOT_SET}"
echo "   UPSTREAM_STT: ${UPSTREAM_STT:-⚠️  NOT_SET}"
echo "   UPSTREAM_TTS: ${UPSTREAM_TTS:-⚠️  NOT_SET}"

# Require IDP so /auth works
if [[ -z "${UPSTREAM_IDP:-}" ]]; then
  echo "❌ FATAL: UPSTREAM_IDP is required (Keycloak upstream)."
  echo "   nginx-edge cannot function without Keycloak routing."
  exit 1
fi

# Normalize upstreams to ensure consistent trailing slash behavior
IDP_UPSTREAM="${UPSTREAM_IDP%/}"
ORCH_UPSTREAM="${UPSTREAM_ORCH:-}"
TTS_UPSTREAM="${UPSTREAM_TTS:-}"
STT_UPSTREAM="${UPSTREAM_STT:-}"

# Remove trailing slashes for consistency
[[ -n "$ORCH_UPSTREAM" ]] && ORCH_UPSTREAM="${ORCH_UPSTREAM%/}"
[[ -n "$TTS_UPSTREAM"  ]] && TTS_UPSTREAM="${TTS_UPSTREAM%/}"
[[ -n "$STT_UPSTREAM"  ]] && STT_UPSTREAM="${STT_UPSTREAM%/}"

echo "✅ Normalized upstreams:"
echo "   IDP: $IDP_UPSTREAM"
[[ -n "$ORCH_UPSTREAM" ]] && echo "   ORCH: $ORCH_UPSTREAM" || echo "   ORCH: ❌ DISABLED"
[[ -n "$STT_UPSTREAM" ]] && echo "   STT: $STT_UPSTREAM" || echo "   STT: ❌ DISABLED"
[[ -n "$TTS_UPSTREAM" ]] && echo "   TTS: $TTS_UPSTREAM" || echo "   TTS: ❌ DISABLED"

CONF="/etc/nginx/nginx.conf"

echo "🔧 Generating nginx configuration..."

# Write full nginx.conf (events + http + server)
# NOTE: We escape NGINX runtime variables like $host as \$host so Bash doesn't expand them.
cat > "$CONF" <<EOF
# Generated nginx configuration for nginx-edge
# Generated at: $(date)
worker_processes  auto;
error_log  /var/log/nginx/error.log warn;
pid        /var/run/nginx.pid;

events {
  worker_connections  1024;
}

http {
  include       /etc/nginx/mime.types;
  default_type  application/octet-stream;
  
  # Logging
  log_format main '\$remote_addr - \$remote_user [\$time_local] "\$request" '
                  '\$status \$body_bytes_sent "\$http_referer" '
                  '"\$http_user_agent" "\$http_x_forwarded_for"';
  
  access_log  /var/log/nginx/access.log  main;

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
    server_name _;

    # Health check endpoint
    location = /healthz { 
      access_log off;
      return 200 'nginx-edge healthy\n';
      add_header Content-Type text/plain;
    }
    
    # Root endpoint - simple status
    location = / {
      return 200 'nginx-edge proxy\n';
      add_header Content-Type text/plain;
    }

    # ---- Keycloak (IDP) - ALWAYS ENABLED ----
    location /auth/ {
      proxy_pass         ${IDP_UPSTREAM}/;
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
      proxy_connect_timeout 10s;
      client_