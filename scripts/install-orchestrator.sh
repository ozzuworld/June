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
echo "Fresh VM -> Full June Platform + Extensions"
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

# Export config for child scripts (including new optional variables)
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

# Export Vast.ai configuration (optional)
export VAST_API_KEY
export VAST_GPU_TYPE
export VAST_MAX_PRICE_PER_HOUR
export VAST_MIN_GPU_MEMORY
export VAST_RELIABILITY_SCORE
export VAST_MIN_DOWNLOAD_SPEED
export VAST_MIN_UPLOAD_SPEED
export VAST_DATACENTER_LOCATION
export VAST_PREFERRED_REGIONS
export VAST_VERIFIED_ONLY
export VAST_RENTABLE_ONLY

# Export Headscale configuration (optional)
export HEADSCALE_DOMAIN
export HEADSCALE_NAMESPACE
export HEADSCALE_USER
export K8S_SERVICE_CIDR
export K8S_POD_CIDR
export ENABLE_TAILSCALE_SIDECARS

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

# Function to detect external IP with multiple fallbacks
get_external_ip() {
    local ip=""
    
    # Try multiple IP detection services
    local services=(
        "http://checkip.amazonaws.com/"
        "https://ifconfig.me"
        "https://ipinfo.io/ip"
        "https://api.ipify.org"
        "http://whatismyip.akamai.com/"
    )
    
    for service in "${services[@]}"; do
        ip=$(curl -s --max-time 10 "$service" 2>/dev/null | tr -d '\n' | grep -oE '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$' || echo "")
        if [ -n "$ip" ] && [[ "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
            echo "$ip"
            return 0
        fi
    done
    
    # Fallback to hostname -I (local IP)
    ip=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "")
    if [ -n "$ip" ] && [[ "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
        echo "$ip"
        return 0
    fi
    
    # Final fallback
    echo "unknown"
    return 1
}

# Define installation phases (REMOVED 08-livekit - now integrated in 09-june-platform)
PHASES=(
    "01-prerequisites"
    "02-docker"
    "02.5-gpu"
    "03-kubernetes"
    "04-infrastructure"
    "05-helm"
    "03.5-gpu-operator"    # GPU Operator after Helm is installed
    "06-certificates"
    "07-stunner"
    "09-june-platform"     # LiveKit now included as part of June platform
    "10-final-setup"
    "11-headscale"          # VPN control plane server
    "11.2-headscale-sidecars" # Add Tailscale sidecars to June services
    "11.5-headscale-node"   # Connect this node to Headscale with subnet routing
    "12-skypilot"           # Remote GPU provider
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
    
    echo ""
    echo "Virtual Nodes (Vast.ai):"
    kubectl get nodes -l type=virtual-kubelet 2>/dev/null || echo "No virtual nodes found"
    
    echo ""
    echo "Headscale Status:"
    kubectl get pods -n headscale 2>/dev/null || echo "Headscale namespace not found"
    
    echo ""
    echo "Tailscale Node Status:"
    tailscale status 2>/dev/null || echo "Tailscale not installed or not connected"
    
    echo ""
    echo "Tailscale Sidecars:"
    kubectl get pods -n june-services -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].name}{"\n"}{end}' 2>/dev/null | grep tailscale || echo "No Tailscale sidecars found"
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
    log "Detecting external IP address..."
    EXTERNAL_IP=$(get_external_ip)
    if [ "$EXTERNAL_IP" = "unknown" ]; then
        warn "Could not detect external IP address automatically"
        echo "Please manually check your public IP and update DNS accordingly"
    else
        success "Detected external IP: $EXTERNAL_IP"
    fi
    
    # Detect GPU availability for final summary
    GPU_AVAILABLE="false"
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        GPU_AVAILABLE="true"
    fi
    
    # Check for Headscale deployment
    HEADSCALE_AVAILABLE="false"
    if kubectl get namespace headscale &>/dev/null; then
        HEADSCALE_AVAILABLE="true"
    fi
    
    # Check for Tailscale node connection
    TAILSCALE_CONNECTED="false"
    if command -v tailscale &>/dev/null && tailscale status &>/dev/null; then
        TAILSCALE_CONNECTED="true"
    fi
    
    # Check for Tailscale sidecars
    TAILSCALE_SIDECARS="false"
    if kubectl get pods -n june-services -o jsonpath='{.items[*].spec.containers[*].name}' 2>/dev/null | grep -q tailscale; then
        TAILSCALE_SIDECARS="true"
    fi
    
    # Check for Vast.ai virtual node
    VAST_NODE=$(kubectl get nodes -l type=virtual-kubelet -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    
    echo ""
    echo "==========================================="
    success "June Platform Installation Complete!"
    echo "==========================================="
    echo ""
    echo "📋 Core Services:"
    echo "  API:        https://api.$DOMAIN"
    echo "  Identity:   https://idp.$DOMAIN"
    if [ "$GPU_AVAILABLE" = "true" ] || [ -n "$VAST_NODE" ]; then
        echo "  STT:        https://stt.$DOMAIN"
        echo "  TTS:        https://tts.$DOMAIN"
    fi
    echo ""
    echo "🎮 WebRTC Services:"
    echo "  LiveKit:    livekit-livekit-server.june-services.svc.cluster.local"
    echo "  TURN:       turn:${EXTERNAL_IP}:3478"
    echo ""
    if [ "$HEADSCALE_AVAILABLE" = "true" ]; then
        echo "🔗 VPN Control Plane (Headscale):"
        echo "  Control:    https://headscale.$DOMAIN"
        echo "  Network:    100.64.0.0/10 (tail.$DOMAIN)"
        echo "  Management: kubectl exec -n headscale deployment/headscale -- headscale"
        if [ "$TAILSCALE_CONNECTED" = "true" ]; then
            echo "  Node Status: ✅ Connected (subnet routes advertised)"
        else
            echo "  Node Status: ⚠️  Not connected (run phase 11.5-headscale-node)"
        fi
        if [ "$TAILSCALE_SIDECARS" = "true" ]; then
            echo "  Sidecars:   ✅ Deployed (services available on tailnet)"
            echo "    • june-orchestrator.tail.$DOMAIN"
            echo "    • june-idp.tail.$DOMAIN"
        else
            echo "  Sidecars:   ⚠️  Not deployed (run phase 11.2-headscale-sidecars)"
        fi
        echo ""
    fi
    if [ -n "$VAST_NODE" ]; then
        echo "☁️ Remote GPU Resources (Vast.ai):"
        echo "  Virtual Node: $VAST_NODE"
        echo "  GPU Services: Automatically scheduled to cost-optimized instances"
        echo "  Management:   kubectl logs -n kube-system deployment/virtual-kubelet-vast"
        echo ""
    fi
    echo "🌐 DNS Configuration:"
    if [ "$EXTERNAL_IP" != "unknown" ]; then
        echo "  Point these records to: $EXTERNAL_IP"
        echo "    $DOMAIN           A    $EXTERNAL_IP"
        echo "    *.$DOMAIN         A    $EXTERNAL_IP"
    else
        echo "  Point these records to YOUR_PUBLIC_IP:"
        echo "    $DOMAIN           A    YOUR_PUBLIC_IP"
        echo "    *.$DOMAIN         A    YOUR_PUBLIC_IP"
        echo "  ⚠️  Get your public IP: curl ifconfig.me"
    fi
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
    echo "  kubectl get pods -n june-services   # Core services"
    echo "  kubectl get gateway -n stunner       # STUNner"
    echo "  kubectl get certificates -n june-services # Certificates"
    if [ "$HEADSCALE_AVAILABLE" = "true" ]; then
        echo "  kubectl get pods -n headscale        # VPN control plane"
        if [ "$TAILSCALE_CONNECTED" = "true" ]; then
            echo "  tailscale status                     # Node VPN status"
        fi
        if [ "$TAILSCALE_SIDECARS" = "true" ]; then
            echo "  kubectl logs -n june-services deployment/june-orchestrator -c tailscale  # Sidecar logs"
        fi
    fi
    if [ -n "$VAST_NODE" ]; then
        echo "  kubectl get nodes -l type=virtual-kubelet # Remote GPU nodes"
    fi
    echo ""
    if [ "$EXTERNAL_IP" = "unknown" ]; then
        echo "🔧 Next Steps:"
        echo "  1. Get your public IP: curl ifconfig.me"
        echo "  2. Update DNS A records to point to your IP"
        echo "  3. Wait 5-10 minutes for DNS propagation"
        echo "  4. Test: curl -k https://api.$DOMAIN/health"
        echo ""
    fi
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
    echo "  $0                                    # Run all phases"
    echo "  $0 --skip 01-prerequisites           # Skip prerequisites"
    echo "  $0 --skip kubernetes docker          # Skip multiple phases"
    echo "  $0 --skip 06-certificates            # Skip certificate management"
    echo "  $0 --skip 02.5-gpu                   # Skip GPU driver/runtime"
    echo "  $0 --skip 03.5-gpu-operator          # Skip GPU Operator/time-slicing"
    echo "  $0 --skip 11-headscale               # Skip VPN control plane"
    echo "  $0 --skip 11.2-headscale-sidecars    # Skip Tailscale sidecars"
    echo "  $0 --skip 11.5-headscale-node        # Skip node subnet routing"
    echo "  $0 --skip 12-vast-gpu                # Skip remote GPU provider"
}

# Check for help flag
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    show_usage
    exit 0
fi

main "$@"