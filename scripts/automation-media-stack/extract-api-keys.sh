#!/bin/bash
# Extract API keys from running media stack pods
# These keys are auto-generated on first start and stored in config files

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; }

log "Extracting API keys from media stack pods..."
echo ""

# Function to extract API key from pod config
extract_api_key() {
    local pod_name=$1
    local namespace=$2
    local config_path=$3
    local output_file=$4

    log "Extracting API key from $pod_name..."

    # Wait for pod to be running
    if ! kubectl wait --for=condition=ready pod -l app=$pod_name -n $namespace --timeout=60s 2>/dev/null; then
        warn "$pod_name not ready yet, skipping"
        return 1
    fi

    # Extract API key from config.xml
    local api_key=$(kubectl exec -n $namespace deployment/$pod_name -- \
        cat $config_path 2>/dev/null | \
        grep -oP '<ApiKey>\K[^<]+' || echo "")

    if [ -z "$api_key" ]; then
        warn "Could not extract API key from $pod_name"
        warn "The pod may not have started yet or config file doesn't exist"
        return 1
    fi

    # Save to file
    echo "$api_key" > "$output_file"
    chmod 600 "$output_file"

    success "$pod_name API key: ${api_key:0:8}... (saved to $output_file)"
    return 0
}

# Extract Prowlarr API key
extract_api_key "prowlarr" "media-stack" "/config/config.xml" "/root/.prowlarr-api-key"

# Extract Sonarr API key
extract_api_key "sonarr" "media-stack" "/config/config.xml" "/root/.sonarr-api-key"

# Extract Radarr API key
extract_api_key "radarr" "media-stack" "/config/config.xml" "/root/.radarr-api-key"

# Extract Lidarr API key
extract_api_key "lidarr" "media-stack" "/config/config.xml" "/root/.lidarr-api-key"

echo ""
success "API key extraction complete!"
echo ""
echo "📁 API keys saved to:"
echo "  /root/.prowlarr-api-key"
echo "  /root/.sonarr-api-key"
echo "  /root/.radarr-api-key"
echo "  /root/.lidarr-api-key"
echo ""
echo "These will be used by automation scripts to configure connections."
