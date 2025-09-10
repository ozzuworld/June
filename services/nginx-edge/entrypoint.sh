#!/usr/bin/env bash
set -euo pipefail

# Required environment variables
: "${PORT:?PORT env var required}"
: "${UPSTREAM_IDP:?UPSTREAM_IDP env var required}"
: "${UPSTREAM_ORCH:?UPSTREAM_ORCH env var required}"
: "${UPSTREAM_STT:?UPSTREAM_STT env var required}"
: "${UPSTREAM_TTS:?UPSTREAM_TTS env var required}"

echo "🔧 Configuring nginx-edge with upstreams:"
echo "   IDP:  $UPSTREAM_IDP"
echo "   ORCH: $UPSTREAM_ORCH"
echo "   STT:  $UPSTREAM_STT"
echo "   TTS:  $UPSTREAM_TTS"
echo "   PORT: $PORT"

# Extract hostnames from URLs (remove https:// and any trailing paths)
IDP_HOST=$(echo "$UPSTREAM_IDP" | sed 's|https\?://||' | sed 's|/.*||')
ORCH_HOST=$(echo "$UPSTREAM_ORCH" | sed 's|https\?://||' | sed 's|/.*||')
STT_HOST=$(echo "$UPSTREAM_STT" | sed 's|https\?://||' | sed 's|/.*||')
TTS_HOST=$(echo "$UPSTREAM_TTS" | sed 's|https\?://||' | sed 's|/.*||')

echo "🔄 Extracted upstream hosts:"
echo "   IDP:  $IDP_HOST"
echo "   ORCH: $ORCH_HOST"
echo "   STT:  $STT_HOST"
echo "   TTS:  $TTS_HOST"

# Generate nginx.conf directly
cat > /etc/nginx/nginx.conf << EOF
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    # Logging format
    log_format main '\$remote_addr - \$remote_user [\$time_local] "\$request" '
                    '\$status \$body_bytes_sent "\$http_referer" '
                    '"\$http_user_agent" "\$http_x_forwarded_for"';
    access_log /var/log/nginx/access.log main;
    
    # Basic settings
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 20M;
    
    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;

    # Upstream definitions (HTTPS backends)
    upstream idp_backend {
        server $IDP_HOST:443;
        keepalive 32;
    }
    
    upstream orchestrator_backend {
        server $ORCH_HOST:443;
        keepalive 32;
    }
    
    upstream stt_backend {
        server $STT_HOST:443;
        keepalive 32;
    }
    
    upstream tts_backend {
        server $TTS_HOST:443;
        keepalive 32;
    }

    # Map for WebSocket connection upgrade
    map \$http_upgrade \$connection_upgrade {
        default upgrade;
        '' close;
    }

    server {
        listen $PORT;
        server_name _;
        
        # Health check (works!)
        location = /healthz {
            return 200 'nginx-edge OK\n';
            add_header Content-Type text/plain;
        }
        
        # Root - redirect to Keycloak admin console
        location = / {
            return 302 /auth/admin/;
        }
        
        # Keycloak (Identity Provider) - strip /auth prefix
        location /auth/ {
            # Remove /auth from the request path when proxying
            rewrite ^/auth/(.*) /\$1 break;
            
            proxy_pass https://idp_backend;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            
            # Preserve original request info
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_set_header X-Forwarded-Host \$host;
            proxy_set_header X-Forwarded-Port \$server_port;
            
            # Timeout settings
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
        
        # Orchestrator service - strip /orchestrator prefix
        location /orchestrator/ {
            # Remove /orchestrator from the request path when proxying
            rewrite ^/orchestrator/(.*) /\$1 break;
            
            proxy_pass https://orchestrator_backend;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            
            # Preserve original request info
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            proxy_set_header X-Forwarded-Host \$host;
            proxy_set_header X-Forwarded-Port \$server_port;
            
            # WebSocket support
            proxy_set_header Upgrade \$http_upgrade;
            proxy_set_header Connection \$connection_upgrade;
            
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
        
        # Speech-to-Text service - strip /stt prefix
        location /stt/ {
            # Remove /stt from the request path when proxying
            rewrite ^/stt/(.*) /\$1 break;
            
            proxy_pass https://stt_backend;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            
            # Preserve original request info
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            
            # WebSocket support for real-time STT
            proxy_set_header Upgrade \$http_upgrade;
            proxy_set_header Connection \$connection_upgrade;
            
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
        
        # Text-to-Speech service - strip /tts prefix
        location /tts/ {
            # Remove /tts from the request path when proxying
            rewrite ^/tts/(.*) /\$1 break;
            
            proxy_pass https://tts_backend;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            
            # Preserve original request info
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
    }
}
EOF

echo "✅ nginx.conf generated successfully"

# Test configuration
echo "🧪 Testing nginx configuration..."
nginx -t

if [ $? -eq 0 ]; then
    echo "✅ nginx configuration is valid"
    echo "🚀 Starting nginx..."
    exec nginx -g 'daemon off;'
else
    echo "❌ nginx configuration test failed"
    echo "📋 Configuration file contents:"
    cat /etc/nginx/nginx.conf
    exit 1
fi