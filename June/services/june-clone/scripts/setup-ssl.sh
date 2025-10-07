#!/bin/bash

# June TTS SSL Certificate Setup Script
# This script automates the complete SSL certificate setup using certbot

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

error() {
    echo -e "${RED}[ERROR] $1${NC}"
    exit 1
}

warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

# Configuration variables (customize these)
DOMAIN=""
EMAIL=""
TTS_PORT="8001"
JUNE_PATH=""
SETUP_METHOD=""

# Function to display usage
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

This script sets up SSL certificates for June TTS service using certbot.

OPTIONS:
    -d, --domain DOMAIN     Your domain name (e.g., tts.yourdomain.com)
    -e, --email EMAIL       Your email for Let's Encrypt notifications
    -p, --port PORT         TTS service port (default: 8001)
    -j, --june-path PATH    Path to June repository
    -m, --method METHOD     Setup method: standalone, webroot, or nginx (default: nginx)
    -h, --help             Show this help message

EXAMPLES:
    $0 -d tts.example.com -e admin@example.com -j /home/user/June
    $0 --domain tts.example.com --email admin@example.com --method standalone

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--domain)
            DOMAIN="$2"
            shift 2
            ;;
        -e|--email)
            EMAIL="$2"
            shift 2
            ;;
        -p|--port)
            TTS_PORT="$2"
            shift 2
            ;;
        -j|--june-path)
            JUNE_PATH="$2"
            shift 2
            ;;
        -m|--method)
            SETUP_METHOD="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            ;;
    esac
done

# Interactive input if parameters not provided
if [[ -z "$DOMAIN" ]]; then
    read -p "Enter your domain name (e.g., tts.yourdomain.com): " DOMAIN
fi

if [[ -z "$EMAIL" ]]; then
    read -p "Enter your email address: " EMAIL
fi

if [[ -z "$JUNE_PATH" ]]; then
    read -p "Enter path to June repository (e.g., /home/user/June): " JUNE_PATH
fi

if [[ -z "$SETUP_METHOD" ]]; then
    echo "Choose SSL setup method:"
    echo "1) nginx (recommended - with reverse proxy)"
    echo "2) standalone (direct certbot)"
    echo "3) webroot (existing web server)"
    read -p "Enter choice [1-3]: " choice
    case $choice in
        1) SETUP_METHOD="nginx" ;;
        2) SETUP_METHOD="standalone" ;;
        3) SETUP_METHOD="webroot" ;;
        *) SETUP_METHOD="nginx" ;;
    esac
fi

# Validation
if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
    error "Domain and email are required!"
fi

if [[ ! -d "$JUNE_PATH" ]]; then
    error "June repository path does not exist: $JUNE_PATH"
fi

log "Starting SSL setup for June TTS service"
info "Domain: $DOMAIN"
info "Email: $EMAIL"
info "TTS Port: $TTS_PORT"
info "June Path: $JUNE_PATH"
info "Setup Method: $SETUP_METHOD"

# Check if running as root or with sudo
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root or with sudo"
fi

# Step 1: Update system and install dependencies
log "Step 1: Installing dependencies..."
apt update -y
apt upgrade -y
apt install -y curl wget snapd nginx python3-pip

# Install snapd core
snap install core
snap refresh core

# Step 2: Install Certbot
log "Step 2: Installing Certbot..."
snap install --classic certbot
ln -sf /snap/bin/certbot /usr/bin/certbot

# Install nginx plugin if using nginx method
if [[ "$SETUP_METHOD" == "nginx" ]]; then
    apt install -y python3-certbot-nginx
fi

# Step 3: Configure firewall
log "Step 3: Configuring firewall..."
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow $TTS_PORT/tcp
ufw --force enable

# Step 4: Stop conflicting services temporarily
log "Step 4: Preparing for certificate generation..."
if [[ "$SETUP_METHOD" == "standalone" ]]; then
    systemctl stop nginx apache2 2>/dev/null || true
fi

# Step 5: Generate SSL certificate
log "Step 5: Generating SSL certificate..."
case "$SETUP_METHOD" in
    "standalone")
        certbot certonly --standalone \
            -d "$DOMAIN" \
            -m "$EMAIL" \
            --agree-tos \
            --non-interactive \
            --force-renewal
        ;;
    "nginx")
        # First create basic nginx config
        cat > "/etc/nginx/sites-available/$DOMAIN" << EOL
server {
    listen 80;
    server_name $DOMAIN;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://\$server_name\$request_uri;
    }
}
EOL
        ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
        nginx -t && systemctl reload nginx

        certbot --nginx \
            -d "$DOMAIN" \
            -m "$EMAIL" \
            --agree-tos \
            --non-interactive
        ;;
    "webroot")
        mkdir -p /var/www/html
        certbot certonly --webroot \
            -w /var/www/html \
            -d "$DOMAIN" \
            -m "$EMAIL" \
            --agree-tos \
            --non-interactive
        ;;
esac

# Step 6: Create nginx configuration for TTS service
log "Step 6: Creating nginx configuration..."
cat > "/etc/nginx/sites-available/$DOMAIN" << EOL
server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;

    # SSL Security
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:50m;
    ssl_stapling on;
    ssl_stapling_verify on;

    # Security headers
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;

    # Proxy to TTS service
    location / {
        proxy_pass http://127.0.0.1:$TTS_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Let's Encrypt challenge
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
}
EOL

# Enable site and restart nginx
ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
nginx -t && systemctl restart nginx

# Step 7: Create SSL configuration for TTS service
log "Step 7: Creating TTS SSL configuration..."
TTS_SERVICE_PATH="$JUNE_PATH/services/june-tts"

if [[ -d "$TTS_SERVICE_PATH" ]]; then
    cat > "$TTS_SERVICE_PATH/ssl_config.py" << EOL
# SSL Configuration for June TTS Service
import ssl
import os

def get_ssl_context():
    """
    Configure SSL context for TTS service
    """
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

    cert_path = "/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    key_path = "/etc/letsencrypt/live/$DOMAIN/privkey.pem"

    if os.path.exists(cert_path) and os.path.exists(key_path):
        ssl_context.load_cert_chain(cert_path, key_path)
        return ssl_context
    else:
        print("SSL certificates not found, running without SSL")
        return None

# SSL-enabled uvicorn configuration
SSL_CONFIG = {
    "ssl_keyfile": "/etc/letsencrypt/live/$DOMAIN/privkey.pem",
    "ssl_certfile": "/etc/letsencrypt/live/$DOMAIN/fullchain.pem",
}
EOL
else
    warning "TTS service path not found, skipping SSL config creation"
fi

# Step 8: Update environment configuration
log "Step 8: Updating environment configuration..."
ENV_FILES=(
    "$JUNE_PATH/.env"
    "$JUNE_PATH/services/june-orchestrator/.env"
    "$JUNE_PATH/services/june-tts/.env"
)

for env_file in "${ENV_FILES[@]}"; do
    if [[ -f "$env_file" ]]; then
        # Backup original
        cp "$env_file" "$env_file.backup.$(date +%Y%m%d_%H%M%S)"

        # Update or add SSL configuration
        sed -i "s|EXTERNAL_TTS_URL=.*|EXTERNAL_TTS_URL=https://$DOMAIN|g" "$env_file"
        sed -i "s|TTS_SERVICE_URL=.*|TTS_SERVICE_URL=https://$DOMAIN|g" "$env_file"

        # Add SSL configuration if not exists
        if ! grep -q "SSL_ENABLED" "$env_file"; then
            cat >> "$env_file" << EOL

# SSL Configuration
SSL_ENABLED=true
SSL_CERT_PATH=/etc/letsencrypt/live/$DOMAIN/fullchain.pem
SSL_KEY_PATH=/etc/letsencrypt/live/$DOMAIN/privkey.pem
HTTPS_DOMAIN=$DOMAIN

# CORS Configuration for HTTPS
CORS_ALLOW_ORIGINS=https://$DOMAIN,https://$(echo $DOMAIN | sed 's/tts\.//'),http://localhost:3000
EOL
        fi

        info "Updated environment file: $env_file"
    fi
done

# Step 9: Create systemd service for TTS (optional)
log "Step 9: Creating systemd service..."
cat > "/etc/systemd/system/june-tts.service" << EOL
[Unit]
Description=June TTS Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=$TTS_SERVICE_PATH
Environment=PATH=$TTS_SERVICE_PATH/venv/bin
ExecStart=$TTS_SERVICE_PATH/venv/bin/python -m app.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

systemctl daemon-reload
systemctl enable june-tts.service

# Step 10: Setup automatic renewal
log "Step 10: Setting up automatic certificate renewal..."
mkdir -p /etc/letsencrypt/renewal-hooks/deploy

cat > "/etc/letsencrypt/renewal-hooks/deploy/restart-services.sh" << EOL
#!/bin/bash
# Restart services after certificate renewal
systemctl reload nginx
systemctl restart june-tts 2>/dev/null || true
echo "Services restarted after certificate renewal at \$(date)"
EOL

chmod +x /etc/letsencrypt/renewal-hooks/deploy/restart-services.sh

# Test automatic renewal
certbot renew --dry-run

# Step 11: Create maintenance script
log "Step 11: Creating maintenance scripts..."
cat > "/usr/local/bin/june-ssl-renew.sh" << EOL
#!/bin/bash
# June TTS SSL Renewal Script

echo "Renewing SSL certificates..."
certbot renew --quiet

echo "Restarting services..."
systemctl reload nginx
systemctl restart june-tts 2>/dev/null || true

echo "SSL renewal completed at \$(date)"
EOL

chmod +x /usr/local/bin/june-ssl-renew.sh

# Create status check script
cat > "/usr/local/bin/june-ssl-status.sh" << EOL
#!/bin/bash
# June TTS SSL Status Check

echo "=== June TTS SSL Status ==="
echo "Domain: $DOMAIN"
echo "Certificate Status:"
certbot certificates | grep -A 10 "$DOMAIN"

echo -e "\n=== Service Status ==="
systemctl status nginx --no-pager -l
systemctl status june-tts --no-pager -l 2>/dev/null || echo "june-tts service not running"

echo -e "\n=== SSL Test ==="
curl -I "https://$DOMAIN/healthz" 2>/dev/null | head -n 5 || echo "HTTPS test failed"

echo -e "\n=== Certificate Expiry ==="
echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN:443" 2>/dev/null | openssl x509 -noout -dates
EOL

chmod +x /usr/local/bin/june-ssl-status.sh

# Final verification
log "Step 12: Final verification..."
sleep 5

# Test nginx configuration
if nginx -t; then
    log "Nginx configuration is valid"
else
    error "Nginx configuration has errors"
fi

# Test SSL certificate
if curl -I "https://$DOMAIN" >/dev/null 2>&1; then
    log "SSL certificate is working"
else
    warning "SSL test failed - check your DNS and firewall settings"
fi

# Set proper permissions for certificates
chmod 644 "/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
chmod 600 "/etc/letsencrypt/live/$DOMAIN/privkey.pem"

log "SSL setup completed successfully!"
echo ""
echo "=== SETUP SUMMARY ==="
info "Domain: https://$DOMAIN"
info "TTS Service: Running on port $TTS_PORT (proxied through nginx)"
info "Certificates: /etc/letsencrypt/live/$DOMAIN/"
info "Nginx Config: /etc/nginx/sites-available/$DOMAIN"
echo ""
echo "=== USEFUL COMMANDS ==="
echo "Check SSL status: june-ssl-status.sh"
echo "Renew certificates: june-ssl-renew.sh"
echo "View logs: journalctl -u nginx -f"
echo "Restart TTS: systemctl restart june-tts"
echo ""
echo "=== TEST YOUR SETUP ==="
echo "curl https://$DOMAIN/healthz"
echo "curl https://$DOMAIN/v1/status"
echo ""
warning "Don't forget to update your June orchestrator to use: https://$DOMAIN"
log "Setup complete! Your June TTS service is now secured with SSL."
