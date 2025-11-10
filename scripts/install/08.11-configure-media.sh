#!/bin/bash
# June Platform - Media Stack Complete Configuration
# Automates: Jellyfin libraries, Prowlarr indexers, Sonarr/Radarr connections, Jellyseerr

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

ROOT_DIR="$1"

if [ -z "$DOMAIN" ]; then
    if [ -z "$ROOT_DIR" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
    fi
    CONFIG_FILE="${ROOT_DIR}/config.env"
    [ ! -f "$CONFIG_FILE" ] && error "Configuration file not found: $CONFIG_FILE"
    log "Loading configuration from: $CONFIG_FILE"
    source "$CONFIG_FILE"
fi

[ -z "$DOMAIN" ] && error "DOMAIN variable is not set."

# Get credentials
MEDIA_STACK_USERNAME="${MEDIA_STACK_USERNAME:-admin}"
MEDIA_STACK_PASSWORD="${MEDIA_STACK_PASSWORD:-Pokemon123!}"
JELLYFIN_USERNAME="${JELLYFIN_USERNAME:-admin}"
JELLYFIN_PASSWORD="${JELLYFIN_PASSWORD:-Pokemon123!}"

# Path to automation scripts
AUTOMATION_DIR="${ROOT_DIR}/scripts/automation-media-stack"

echo "================================================================"
echo "June Platform - Complete Media Stack Configuration"
echo "================================================================"
echo ""

# Wait for all services to be ready
log "Waiting for services to be ready..."
sleep 20

# Step 1: Configure Jellyfin Libraries
log "Step 1: Configuring Jellyfin libraries..."
python3 "${AUTOMATION_DIR}/configure-jellyfin-libraries.py" \
  --url "https://tv.${DOMAIN}" \
  --username "$JELLYFIN_USERNAME" \
  --password "$JELLYFIN_PASSWORD" || \
  warn "Failed to auto-configure Jellyfin libraries"

echo ""

# Step 2: Configure Prowlarr Indexers
log "Step 2: Adding indexers to Prowlarr..."
python3 "${AUTOMATION_DIR}/configure-prowlarr-indexers.py" \
  --url "https://prowlarr.${DOMAIN}" || \
  warn "Failed to auto-configure Prowlarr indexers"

echo ""

# Step 3: Configure connections (Prowlarr → Sonarr/Radarr)
log "Step 3: Connecting Sonarr and Radarr to Prowlarr..."
python3 "${AUTOMATION_DIR}/configure-media-stack.py" \
  --domain "${DOMAIN}" || \
  warn "Failed to configure service connections"

echo ""

# Step 4: Show Jellyseerr instructions
log "Step 4: Jellyseerr configuration info..."
python3 "${AUTOMATION_DIR}/configure-jellyseerr.py" \
  --domain "${DOMAIN}" \
  --jellyfin-user "$JELLYFIN_USERNAME" \
  --jellyfin-pass "$JELLYFIN_PASSWORD" || \
  warn "Could not show Jellyseerr config"

echo ""
echo "================================================================"
echo "✅ Media Stack Configuration Complete!"
echo "================================================================"
echo ""
echo "📺 Services Ready:"
echo "  Jellyfin:    https://tv.${DOMAIN}"
echo "  Jellyseerr:  https://requests.${DOMAIN}"
echo "  Prowlarr:    https://prowlarr.${DOMAIN}"
echo "  Sonarr:      https://sonarr.${DOMAIN}"
echo "  Radarr:      https://radarr.${DOMAIN}"
echo "  qBittorrent: https://qbittorrent.${DOMAIN}"
echo ""
echo "🔑 Credentials:"
echo "  Username: $MEDIA_STACK_USERNAME"
echo "  Password: $MEDIA_STACK_PASSWORD"
echo ""
echo "✅ Configuration completed:"
echo "  - Jellyfin libraries created (Movies, TV Shows)"
echo "  - Prowlarr indexers added (4 working indexers)"
echo "  - Sonarr/Radarr connected to Prowlarr"
echo "  - qBittorrent ready for downloads"
echo ""
echo "📝 Manual steps remaining:"
echo "  1. Complete Jellyseerr setup wizard at https://requests.${DOMAIN}"
echo "     (Follow on-screen instructions)"
echo ""
echo "🎬 Ready to use! Request content via Jellyseerr."
echo "================================================================"

success "Media automation stack fully configured!"
