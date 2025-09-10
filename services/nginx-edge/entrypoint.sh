#!/usr/bin/env bash
set -euo pipefail

# CORRECT nginx entrypoint script (replaces the Python test script!)
# This was the problem - your entrypoint.sh was Python, not bash

echo "🚀 Starting nginx-edge configuration..."

# Environment variables from Cloud Run deployment
PORT=${PORT:-8080}
: "${UPSTREAM_IDP:?UPSTREAM_IDP required}"
: "${UPSTREAM_ORCH:?UPSTREAM_ORCH required}" 
: "${UPSTREAM_STT:?UPSTREAM_STT required}"
: "${UPSTREAM_TTS:?UPSTREAM_TTS required}"

echo "Environment check:"
echo "  PORT: $PORT"
echo "  IDP:  $UPSTREAM_IDP"
echo "  ORCH: $UPSTREAM_ORCH"
echo "  STT:  $UPSTREAM_STT"
echo "  TTS:  $UPSTREAM_TTS"

# Extract hostnames (remove https:// prefix)
IDP_HOST=$(echo "$UPSTREAM_IDP" | sed 's|https://||' | sed 's|/.*||')
ORCH_HOST=$(echo "$UPSTREAM_ORCH" | sed 's|https://||' | sed 's|/.*||')
STT_HOST=$(echo "$UPSTREAM_STT" | sed 's|https://||' | sed 's|/.*||')
TTS_HOST=$(echo "$UPSTREAM_TTS" | sed 's|https://||' | sed 's|/.*||')

echo "Extracted hosts:"
echo "  IDP:  $IDP_HOST"
echo "  ORCH: $ORCH_HOST"
echo "  STT:  $STT_HOST"
echo "  TTS:  $TTS_HOST"

# Create nginx configuration
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
    client_max_body_size 20M;
    
    # Compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;

    # Backend server definitions
    upstream idp_backend {
        server IDP_HOST_PLACEHOLDER:443;
        keepalive 8;
    }
    
    upstream orch_backend {
        server ORCH_HOST_PLACEHOLDER:443;
        keepalive 8;
    }
    
    upstream stt_backend {
        server STT_HOST_PLACEHOLDER:443;
        keepalive 8;
    }
    
    upstream tts_backend {
        server TTS_HOST_PLACEHOLDER:443;
        keepalive 8;
    }

    # WebSocket upgrade mapping
    map $http_upgrade $connection_upgrade {
        default upgrade;
        '' close;
    }

    server {
        listen PORT_PLACEHOLDER;
        server_name _;
        
        # Health check
        location = /healthz {
            return 200 "nginx-edge healthy\n";
            add_header Content-Type text/plain;
        }
        
        # Root redirect
        location = / {
            return 302 /auth/admin/;
        }
        
        # Keycloak IDP routes
        location /auth/ {
            # Rewrite /auth/path to /path when proxying
            rewrite ^/auth/(.*)$ /$1 break;
            
            proxy_pass https://idp_backend;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            
            # Headers for proper proxying
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host $host;
            proxy_set_header X-Forwarded-Port $server_port;
            
            # Timeouts
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
        
        # Orchestrator routes
        location /orchestrator/ {
            # Rewrite /orchestrator/path to /path when proxying
            rewrite ^/orchestrator/(.*)$ /$1 break;
            
            proxy_pass https://orch_backend;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            
            # Headers
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host $host;
            proxy_set_header X-Forwarded-Port $server_port;
            
            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            
            # Timeouts
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
        
        # STT routes
        location /stt/ {
            # Rewrite /stt/path to /path when proxying
            rewrite ^/stt/(.*)$ /$1 break;
            
            proxy_pass https://stt_backend;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            
            # Headers
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            
            # Timeouts
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
        
        # TTS routes
        location /tts/ {
            # Rewrite /tts/path to /path when proxying
            rewrite ^/tts/(.*)$ /$1 break;
            
            proxy_pass https://tts_backend;
            proxy_ssl_server_name on;
            proxy_ssl_verify off;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            
            # Headers
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # Timeouts
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
    }
}
EOF

echo "Substituting placeholders in nginx.conf..."

# Replace placeholders in the config file
sed -i "s/IDP_HOST_PLACEHOLDER/$IDP_HOST/g" /etc/nginx/nginx.conf
sed -i "s/ORCH_HOST_PLACEHOLDER/$ORCH_HOST/g" /etc/nginx/nginx.conf
sed -i "s/STT_HOST_PLACEHOLDER/$STT_HOST/g" /etc/nginx/nginx.conf
sed -i "s/TTS_HOST_PLACEHOLDER/$TTS_HOST/g" /etc/nginx/nginx.conf
sed -i "s/PORT_PLACEHOLDER/$PORT/g" /etc/nginx/nginx.conf

echo "Testing nginx configuration..."
nginx -t

if [ $? -eq 0 ]; then
    echo "✅ nginx configuration is valid"
    echo "🚀 Starting nginx server..."
    exec nginx -g 'daemon off;'
else
    echo "❌ nginx configuration failed validation"
    echo "Configuration file:"
    cat /etc/nginx/nginx.conf
    exit 1
fi