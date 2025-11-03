#!/bin/bash
# June Platform - Installation Orchestrator
# Coordinates installation of all components using modular scripts

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

echo "==========================================="
echo "June Platform - Modular Installation"
echo "Fresh VM -> Full June Platform + LiveKit"
echo "==========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    error "Please run as root (sudo ./scripts/install-orchestrator.sh)"
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Configuration file
CONFIG_FILE="${ROOT_DIR}/config.env"

if [ ! -f "$CONFIG_FILE" ]; then
    error "Configuration file not found: $CONFIG_FILE
    
Please create it first:
  cp config.env.example config.env
  nano config.env
"
fi

log "Loading configuration from: $CONFIG_FILE"
source "$CONFIG_FILE"

# Export config for child scripts
export CONFIG_FILE
export DOMAIN
export LETSENCRYPT_EMAIL
export GEMINI_API_KEY
export CLOUDFLARE_TOKEN
export POSTGRESQL_PASSWORD
export KEYCLOAK_ADMIN_PASSWORD
export TURN_USERNAME
export STUNNER_PASSWORD
export GPU_TIMESLICING_REPLICAS

# Validate required variables
REQUIRED_VARS=(
    "DOMAIN"
    "LETSENCRYPT_EMAIL"
    "GEMINI_API_KEY"
    "CLOUDFLARE_TOKEN"
)

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        error "Required variable $var is not set in $CONFIG_FILE"
    fi
done

success "Configuration loaded"
log "Domain: $DOMAIN"

# Define installation phases (ensure Helm before Redis)
PHASES=(
    "01-prerequisites"
    "02-docker"
    "02.5-gpu"
    "03-kubernetes"
    "04-infrastructure"
    "05-helm"           # Ensure helm is installed before Redis helm chart
    "04.5-redis"        # New: Redis deployment via Helm
    "03.5-gpu-operator" # After Helm is installed
    "06-certificates"
    "07-stunner"
    "08-livekit"
    "09-june-platform"
    "10-final-setup"
)

# Function to run a phase
run_phase() {
    local phase="$1"
    local script_file="${SCRIPT_DIR}/install/${phase}.sh"
    
    if [ ! -f "$script_file" ]; then
        error "Phase script not found: $script_file"
    fi
    
    log "Starting phase: $phase"
    
    # Make script executable and run it
    chmod +x "$script_file"
    if bash "$script_file" "$ROOT_DIR"; then
        success "Phase completed: $phase"
    else
        error "Phase failed: $phase"
    fi
}

# Function to show installation progress
show_progress() {
    local current="$1"
    local total="${#PHASES[@]}"
    local percent=$((current * 100 / total))
    
    echo ""
    echo "========================================="
    echo "Progress: [$current/$total] ($percent%)"
    echo "========================================="
    echo ""
}

# Debug function for troubleshooting
debug_info() {
    echo ""
    echo "==========================================="
    echo "Debug Information"
    echo "==========================================="
    
    echo "Kubernetes Nodes:"
    kubectl get nodes -o wide 2>/dev/null || echo "Failed to get nodes"
    
    echo ""
    echo "All Namespaces:"
    kubectl get ns 2>/dev/null || echo "Failed to get namespaces"
    
    echo ""
    echo "cert-manager status:"
    kubectl get pods -n cert-manager 2>/dev/null || echo "cert-manager namespace not found"
    
    echo ""
    echo "Available CRDs (cert-manager):"
    kubectl get crd | grep cert-manager 2>/dev/null || echo "No cert-manager CRDs found"
    
    echo ""
    echo "Certificates status:"
    kubectl get certificates -A 2>/dev/null || echo "No certificates found"
    
    echo ""
    echo "Certificate backups:"
    ls -la /root/.june-certs/ 2>/dev/null || echo "No certificate backups found"
    
    echo ""
    echo "GPU Information:"
    lspci | grep -i nvidia 2>/dev/null || echo "No NVIDIA GPU found"
    nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
}

# Main execution function
main() {
    # Trap to show debug info on error
    trap 'echo ""; echo "Installation failed. Showing debug info:"; debug_info' ERR
    
    local total_phases="${#PHASES[@]}"
    
    # Skip phases if --skip flag is provided
    local skip_phases=()
    if [ "$1" = "--skip" ]; then
        shift
        skip_phases=("$@")
    fi
    
    # Run installation phases
    for i in "${!PHASES[@]}"; do
        local phase="${PHASES[i]}"
        local phase_num=$((i + 1))
        
        # Check if phase should be skipped
        local should_skip=false
        for skip_phase in "${skip_phases[@]}"; do
            if [ "$phase" = "$skip_phase" ] || [ "$skip_phase" = "$(echo $phase | cut -d'-' -f2-)" ]; then
                should_skip=true
                break
            fi
        done
        
        if [ "$should_skip" = true ]; then
            warn "Skipping phase: $phase"
            continue
        fi
        
        show_progress "$phase_num" 
        run_phase "$phase"
    done
    
    # Get external IP for final summary
    EXTERNAL_IP=$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')
    
    # Detect GPU availability for final summary
    GPU_AVAILABLE="false"
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        GPU_AVAILABLE="true"
    fi
    
    echo ""
    echo "==========================================="
    success "June Platform Installation Complete!"
    echo "==========================================="
    echo ""
    echo "📋 Your Services:"
    echo "  API:        https://api.$DOMAIN"
    echo "  Identity:   https://idp.$DOMAIN"
    if [ "$GPU_AVAILABLE" = "true" ]; then
        echo "  STT:        https://stt.$DOMAIN"
        echo "  TTS:        https://tts.$DOMAIN"
    fi
    echo ""
    echo "🎮 WebRTC Services:"
    echo "  LiveKit:    livekit-livekit-server.june-services.svc.cluster.local"
    echo "  TURN:       turn:${EXTERNAL_IP}:3478"
    echo ""
    echo "🌐 DNS Configuration:"
    echo "  Point these records to: $EXTERNAL_IP"
    echo "    $DOMAIN           A    $EXTERNAL_IP"
    echo "    *.$DOMAIN         A    $EXTERNAL_IP"
    echo ""
    echo "🔐 Access Credentials:"
    echo "  Keycloak Admin: https://idp.$DOMAIN/admin"
    echo "    Username: admin"
    echo "    Password: ${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}"
    echo ""
    echo "  TURN Server: turn:${EXTERNAL_IP}:3478"
    echo "    Username: ${TURN_USERNAME:-june-user}"
    echo "    Password: ${STUNNER_PASSWORD:-Pokemon123!}"
    echo ""
    echo "🔒 Certificate Management:"
    echo "  Backup Directory: /root/.june-certs/"
    echo "  Current Certificate: ${DOMAIN//\./-}-wildcard-tls"
    echo "  Backup File: /root/.june-certs/${DOMAIN}-wildcard-tls-backup.yaml"
    echo ""
    echo "📊 Status Check:"
    echo "  kubectl get pods -n june-services   # Core services & LiveKit"
    echo "  kubectl get gateway -n stunner       # STUNner"
    echo "  kubectl get certificates -n june-services # Certificates"
    echo ""
    echo "==========================================="
}

# Show usage information
show_usage() {
    echo "Usage: $0 [--skip phase1 phase2 ...]"
    echo ""
    echo "Available phases to skip:"
    for phase in "${PHASES[@]}"; do
        echo "  - $phase"
    done
    echo ""
    echo "Examples:"
    echo "  $0                              # Run all phases"
    echo "  $0 --skip 01-prerequisites     # Skip prerequisites"
    echo "  $0 --skip kubernetes docker    # Skip multiple phases"
    echo "  $0 --skip 06-certificates      # Skip certificate management"
    echo "  $0 --skip 02.5-gpu             # Skip GPU driver/runtime"
    echo "  $0 --skip 03.5-gpu-operator    # Skip GPU Operator/time-slicing"
}

# Check for help flag
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    show_usage
    exit 0
fi

main "$@"
