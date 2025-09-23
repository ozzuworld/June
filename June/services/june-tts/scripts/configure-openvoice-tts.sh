#!/bin/bash
# configure-openvoice-tts.sh
# Configuration and testing script for OpenVoice TTS service integration with June AI Platform

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

# Configuration
INSTALL_DIR="/opt/openvoice-tts"
SERVICE_NAME="openvoice-tts"
SERVICE_PORT="8080"

echo "🔧 OpenVoice TTS Configuration & Testing"
echo "========================================"
echo ""

# Function to test service endpoints
test_endpoints() {
    log "🧪 Testing service endpoints..."
    
    # Test health endpoint
    echo "1. Health Check:"
    if curl -f -s http://localhost:8080/health >/dev/null 2>&1; then
        success "Health endpoint responding"
        curl -s http://localhost:8080/health | python3 -m json.tool
    else
        error "Health endpoint not responding"
    fi
    
    echo ""
    echo "2. Available Voices:"
    if curl -f -s http://localhost:8080/v1/voices >/dev/null 2>&1; then
        success "Voices endpoint responding"
        curl -s http://localhost:8080/v1/voices | python3 -m json.tool
    else
        warning "Voices endpoint not responding"
    fi
    
    echo ""
    echo "3. Service Status:"
    systemctl status openvoice-tts --no-pager | head -3
}

# Function to create test JWT token (for testing without June IDP)
create_test_token() {
    log "🎫 Creating test JWT token for development..."
    
    cat > /tmp/create_test_token.py << 'EOF'
import jwt
import time
from datetime import datetime, timedelta

# Test payload (matches June IDP format)
payload = {
    "iss": "https://june-idp.allsafe.world/auth/realms/june",
    "sub": "test-user-id",
    "aud": "account",
    "exp": int(time.time()) + 3600,  # 1 hour
    "iat": int(time.time()),
    "auth_time": int(time.time()),
    "typ": "Bearer",
    "azp": "test-client",
    "preferred_username": "test-user"
}

# Create token (using same secret as service for testing)
token = jwt.encode(payload, "test-secret-key", algorithm="HS256")
print(token)
EOF

    python3 /tmp/create_test_token.py
    rm /tmp/create_test_token.py
}

# Function to test TTS with sample text
test_tts_generation() {
    log "🎵 Testing TTS generation..."
    
    # Create test token
    TEST_TOKEN=$(create_test_token)
    
    echo "Testing TTS with sample text..."
    
    # Test simple TTS
    if curl -f -s \
        -H "Authorization: Bearer $TEST_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"text": "Hello, this is a test of the OpenVoice TTS system integrated with June AI Platform", "voice": "default", "language": "EN"}' \
        http://localhost:8080/v1/tts \
        -o /tmp/test_tts_output.wav >/dev/null 2>&1; then
        
        success "TTS generation successful"
        echo "Output saved to: /tmp/test_tts_output.wav"
        echo "File size: $(stat -c%s /tmp/test_tts_output.wav) bytes"
        
        # Test if it's valid audio
        if command -v file >/dev/null && file /tmp/test_tts_output.wav | grep -q "WAVE"; then
            success "Generated valid WAV audio file"
        else
            warning "Generated file may not be valid audio"
        fi
    else
        warning "TTS generation test failed"
    fi
}

# Function to configure SSL with Let's Encrypt
configure_ssl() {
    log "🔒 Configuring SSL with Let's Encrypt..."
    
    # Install certbot
    apt-get update
    apt-get install -y certbot python3-certbot-nginx
    
    read -p "Enter your domain name (e.g., tts.allsafe.world): " DOMAIN_NAME
    
    if [[ -z "$DOMAIN_NAME" ]]; then
        warning "No domain provided, skipping SSL configuration"
        return
    fi
    
    # Get certificate
    certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --email admin@allsafe.world
    
    # Set up auto-renewal
    crontab -l | { cat; echo "0 12 * * * /usr/bin/certbot renew --quiet"; } | crontab -
    
    success "SSL certificate configured for $DOMAIN_NAME"
}

# Function to optimize for GPU usage
optimize_gpu() {
    log "🔥 Optimizing for GPU usage..."
    
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        warning "NVIDIA GPU not detected, skipping GPU optimization"
        return
    fi
    
    # Update systemd service for GPU access
    cat > /etc/systemd/system/openvoice-tts.service.d/gpu.conf << EOF
[Service]
Environment=CUDA_VISIBLE_DEVICES=0
Environment=TORCH_CUDA_ARCH_LIST="6.0;6.1;7.0;7.5;8.0;8.6"
EOF

    systemctl daemon-reload
    systemctl restart openvoice-tts
    
    success "GPU optimization applied"
}

# Function to set up monitoring
setup_monitoring() {
    log "📊 Setting up service monitoring..."
    
    # Create monitoring script
    cat > /usr/local/bin/openvoice-monitor << 'EOF'
#!/bin/bash
# OpenVoice TTS monitoring script

LOG_FILE="/var/log/openvoice-tts/monitor.log"
ALERT_EMAIL="admin@allsafe.world"

# Check service health
check_health() {
    if ! curl -f -s http://localhost:8080/health >/dev/null 2>&1; then
        echo "$(date): OpenVoice TTS service health check failed" >> "$LOG_FILE"
        # Restart service
        systemctl restart openvoice-tts
        echo "$(date): Service restarted" >> "$LOG_FILE"
        return 1
    fi
    return 0
}

# Check memory usage
check_memory() {
    MEM_USAGE=$(ps -o pid,ppid,cmd,%mem,%cpu --sort=-%mem -C python3 | grep openvoice | awk '{print $4}' | head -1)
    if [[ -n "$MEM_USAGE" ]] && (( $(echo "$MEM_USAGE > 80" | bc -l) )); then
        echo "$(date): High memory usage: ${MEM_USAGE}%" >> "$LOG_FILE"
        return 1
    fi
    return 0
}

# Main monitoring function
main() {
    if check_health && check_memory; then
        echo "$(date): All checks passed" >> "$LOG_FILE"
    else
        echo "$(date): Some checks failed" >> "$LOG_FILE"
    fi
}

main
EOF

    chmod +x /usr/local/bin/openvoice-monitor
    
    # Set up cron job for monitoring
    (crontab -l 2>/dev/null; echo "*/5 * * * * /usr/local/bin/openvoice-monitor") | crontab -
    
    success "Monitoring configured (runs every 5 minutes)"
}

# Function to create production configuration
create_production_config() {
    log "⚙️ Creating production configuration..."
    
    # Update systemd service for production
    cat > /etc/systemd/system/openvoice-tts.service.d/production.conf << EOF
[Service]
# Production environment variables
Environment=PYTHONUNBUFFERED=1
Environment=ENVIRONMENT=production
Environment=LOG_LEVEL=INFO

# Security
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/opt/openvoice-tts /var/log/openvoice-tts /tmp

# Resource limits for production
MemoryMax=6G
CPUQuota=400%
TasksMax=1000

# Restart policy
RestartSec=30
StartLimitInterval=60
StartLimitBurst=3
EOF

    # Create production nginx config with rate limiting
    cat > /etc/nginx/sites-available/openvoice-tts-prod << 'EOF'
# Rate limiting
limit_req_zone $binary_remote_addr zone=tts_limit:10m rate=10r/m;
limit_req_zone $binary_remote_addr zone=clone_limit:10m rate=2r/m;

upstream openvoice_backend {
    server 127.0.0.1:8080;
    keepalive 32;
}

server {
    listen 80;
    server_name tts.allsafe.world;
    
    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Referrer-Policy "strict-origin-when-cross-origin";
    
    # Logging
    access_log /var/log/nginx/openvoice-access.log;
    error_log /var/log/nginx/openvoice-error.log;
    
    # Health check (no rate limit)
    location /health {
        proxy_pass http://openvoice_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # TTS endpoint with rate limiting
    location /v1/tts {
        limit_req zone=tts_limit burst=5 nodelay;
        
        proxy_pass http://openvoice_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts for TTS processing
        proxy_read_timeout 300;
        proxy_connect_timeout 60;
        proxy_send_timeout 300;
        
        client_max_body_size 1M;
    }
    
    # Voice cloning endpoint with stricter rate limiting
    location /v1/clone {
        limit_req zone=clone_limit burst=2 nodelay;
        
        proxy_pass http://openvoice_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Longer timeouts for voice cloning
        proxy_read_timeout 600;
        proxy_connect_timeout 60;
        proxy_send_timeout 600;
        
        client_max_body_size 50M;
    }
    
    # Other endpoints
    location / {
        proxy_pass http://openvoice_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_read_timeout 60;
        proxy_connect_timeout 60;
        proxy_send_timeout 60;
    }
}
EOF

    # Enable production config
    ln -sf /etc/nginx/sites-available/openvoice-tts-prod /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/openvoice-tts
    
    # Reload services
    systemctl daemon-reload
    systemctl restart openvoice-tts
    nginx -t && systemctl reload nginx
    
    success "Production configuration applied"
}

# Function to integrate with June AI Platform
integrate_with_june() {
    log "🔗 Integrating with June AI Platform..."
    
    echo "To integrate with your June AI Platform:"
    echo ""
    echo "1. Get the external TTS URL:"
    EXTERNAL_IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")
    echo "   External TTS URL: http://$EXTERNAL_IP"
    echo ""
    echo "2. Encode for Kubernetes secret:"
    ENCODED_URL=$(echo -n "http://$EXTERNAL_IP" | base64)
    echo "   Base64 encoded: $ENCODED_URL"
    echo ""
    echo "3. Update June platform secret:"
    echo "   kubectl patch secret june-secrets -n june-services \\"
    echo "     --patch='{\"data\":{\"EXTERNAL_TTS_URL\":\"$ENCODED_URL\"}}'"
    echo ""
    echo "4. Restart June orchestrator:"
    echo "   kubectl rollout restart deployment/june-orchestrator -n june-services"
    echo ""
    echo "5. Test integration:"
    echo "   kubectl port-forward -n june-services service/june-orchestrator 8080:8080"
    echo "   curl http://localhost:8080/healthz"
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  test           - Test all endpoints and functionality"
    echo "  ssl            - Configure SSL with Let's Encrypt"
    echo "  gpu            - Optimize for GPU usage"
    echo "  monitor        - Set up monitoring"
    echo "  production     - Apply production configuration"
    echo "  integrate      - Show June AI Platform integration steps"
    echo "  all            - Run test, monitor, and production setup"
    echo ""
    echo "If no command is provided, runs basic tests."
}

# Main script logic
case "${1:-test}" in
    "test")
        test_endpoints
        echo ""
        test_tts_generation
        ;;
    "ssl")
        configure_ssl
        ;;
    "gpu")
        optimize_gpu
        ;;
    "monitor")
        setup_monitoring
        ;;
    "production")
        create_production_config
        ;;
    "integrate")
        integrate_with_june
        ;;
    "all")
        test_endpoints
        test_tts_generation
        setup_monitoring
        create_production_config
        echo ""
        log "🎉 Full configuration completed!"
        integrate_with_june
        ;;
    "help"|"-h"|"--help")
        show_usage
        ;;
    *)
        error "Unknown command: $1. Use 'help' to see available commands."
        ;;
esac

echo ""
success "Configuration script completed! 🎵"
