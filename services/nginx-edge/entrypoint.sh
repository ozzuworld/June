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

# Generate nginx.conf directly (no template needed)
cat > /etc/nginx/nginx.conf << 'EOF'
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    # Logging
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';
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
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;

    # Upstream definitions
    upstream idp_backend {
        server UPSTREAM_IDP_HOST;
        keepalive 32;
    }
    
    upstream orchestrator_backend {
        server UPSTREAM_ORCH_HOST;
        keepalive 32;
    }
    
    upstream stt_backend {
        server UPSTREAM_STT_HOST;
        keepalive 32;
    }
    
    upstream tts_backend {
        server UPSTREAM_TTS_HOST;
        keepalive 32;
    }

    server {
        listen PORT_PLACEHOLDER;
        server_name _;
        
        # Health check
        location = /healthz {
            return 200 'OK\n';
            add_header Content-Type text/plain;
        }
        
        # Root redirect to Keycloak admin
        location = / {
            return 302 /auth/admin/;
        }
        
        # Keycloak (Identity Provider)
        location /auth/ {
            proxy_pass https://idp_backend/;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host $host;
            proxy_set_header X-Forwarded-Port $server_port;
            
            # Timeout settings
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
        
        # Orchestrator service
        location /orchestrator/ {
            proxy_pass https://orchestrator_backend/;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host $host;
            proxy_set_header X-Forwarded-Port $server_port;
            
            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
        
        # Speech-to-Text service
        location /stt/ {
            proxy_pass https://stt_backend/;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # WebSocket support for real-time STT
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
        
        # Text-to-Speech service
        location /tts/ {
            proxy_pass https://tts_backend/;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
    }
    
    # WebSocket connection upgrade mapping
    map $http_upgrade $connection_upgrade {
        default upgrade;
        '' close;
    }
}
EOF

# Extract hostnames from URLs and substitute into nginx.conf
IDP_HOST=$(echo "$UPSTREAM_IDP" | sed 's|https\?://||' | sed 's|/.*||')
ORCH_HOST=$(echo "$UPSTREAM_ORCH" | sed 's|https\?://||' | sed 's|/.*||')
STT_HOST=$(echo "$UPSTREAM_STT" | sed 's|https\?://||' | sed 's|/.*||')
TTS_HOST=$(echo "$UPSTREAM_TTS" | sed 's|https\?://||' | sed 's|/.*||')

echo "🔄 Extracted upstream hosts:"
echo "   IDP:  $IDP_HOST"
echo "   ORCH: $ORCH_HOST"
echo "   STT:  $STT_HOST"
echo "   TTS:  $TTS_HOST"

# Replace placeholders in nginx.conf
sed -i "s/UPSTREAM_IDP_HOST/$IDP_HOST/g" /etc/nginx/nginx.conf
sed -i "s/UPSTREAM_ORCH_HOST/$ORCH_HOST/g" /etc/nginx/nginx.conf
sed -i "s/UPSTREAM_STT_HOST/$STT_HOST/g" /etc/nginx/nginx.conf
sed -i "s/UPSTREAM_TTS_HOST/$TTS_HOST/g" /etc/nginx/nginx.conf
sed -i "s/PORT_PLACEHOLDER/$PORT/g" /etc/nginx/nginx.conf

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