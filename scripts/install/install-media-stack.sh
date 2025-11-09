#!/bin/bash
# June Platform - Complete Media Stack Installation
# One-command deployment of entire media automation stack

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Source configuration
source "${ROOT_DIR}/config.env"

echo "================================================================"
echo "Installing Complete Media Automation Stack"
echo "================================================================"
echo ""

# Run all installation phases in order
PHASES=(
    "08.5-jellyfin.sh"
    "08.6-prowlarr.sh"
    "08.7-sonarr.sh"
    "08.8-radarr.sh"
    "08.9-jellyseerr.sh"
    "08.10-qbittorrent.sh"
    "08.11-configure-media-stack.sh"
)

for phase in "${PHASES[@]}"; do
    echo ""
    echo "================================================================"
    echo "Running: $phase"
    echo "================================================================"
    bash "${SCRIPT_DIR}/${phase}" "${ROOT_DIR}" || {
        echo "ERROR: Failed to run $phase"
        exit 1
    }
done

echo ""
echo "================================================================"
echo "✅ Complete Media Stack Installed Successfully!"
echo "================================================================"
echo ""
echo "Access your services:"
echo "  Jellyfin:   https://tv.${DOMAIN}"
echo "  Jellyseerr: https://requests.${DOMAIN}"
echo ""
echo "Login with:"
echo "  Username: ${MEDIA_STACK_USERNAME:-admin}"
echo "  Password: ${MEDIA_STACK_PASSWORD:-Pokemon123!}"
