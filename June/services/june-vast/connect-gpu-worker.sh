#!/bin/bash
# Connect GPU Worker VM to Headscale VPN
# Run this script on the GPU worker VM (not the K8s VM)

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }
info() { echo -e "${BLUE}ℹ️${NC} $1"; }

# Configuration
HEADSCALE_SERVER="headscale.ozzu.world"
HEADSCALE_USER="gpu-worker"
WORKER_HOSTNAME="${1:-gpu-worker-$(hostname)}"

echo "==========================================="
echo "Headscale VPN Client Setup - GPU Worker"
echo "==========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    error "Please run as root (sudo ./connect-gpu-worker.sh)"
fi

check_headscale_server() {
    log "Checking Headscale server availability..."
    
    if curl -sf --connect-timeout 5 "https://${HEADSCALE_SERVER}/health" > /dev/null 2>&1; then
        success "Headscale server is reachable at https://${HEADSCALE_SERVER}"
    else
        error "Cannot reach Headscale server at https://${HEADSCALE_SERVER}
        
Please ensure:
  1. Headscale is running on your K8s cluster
  2. DNS is configured correctly
  3. Firewall allows HTTPS (443) traffic"
    fi
}

install_tailscale() {
    log "Installing Tailscale client..."
    
    # Check if already installed
    if command -v tailscale &>/dev/null; then
        success "Tailscale already installed ($(tailscale version))"
        return 0
    fi
    
    # Detect OS
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VERSION_CODENAME=${VERSION_CODENAME:-$(echo $VERSION_ID | tr -d '.')}
    else
        error "Cannot detect OS. Please install Tailscale manually."
    fi
    
    log "Detected OS: $OS"
    
    # Install based on OS
    case $OS in
        ubuntu|debian)
            log "Installing for Ubuntu/Debian..."
            
            # Determine Ubuntu version
            if [[ "$VERSION_CODENAME" == "noble" ]] || [[ "$VERSION_ID" == "24.04" ]]; then
                CODENAME="noble"
            elif [[ "$VERSION_CODENAME" == "jammy" ]] || [[ "$VERSION_ID" == "22.04" ]]; then
                CODENAME="jammy"
            elif [[ "$VERSION_CODENAME" == "focal" ]] || [[ "$VERSION_ID" == "20.04" ]]; then
                CODENAME="focal"
            else
                CODENAME="jammy" # Default to 22.04
                warn "Unknown Ubuntu version, defaulting to jammy"
            fi
            
            log "Using repository for: $CODENAME"
            
            # Add Tailscale repository
            curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${CODENAME}.noarmor.gpg" | \
                tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
            
            curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${CODENAME}.tailscale-keyring.list" | \
                tee /etc/apt/sources.list.d/tailscale.list
            
            log "Updating package list..."
            apt-get update -qq
            
            log "Installing Tailscale..."
            apt-get install -y tailscale -qq
            ;;
            
        centos|rhel|fedora|rocky|almalinux)
            log "Installing for RHEL/CentOS/Fedora..."
            
            # Add Tailscale repository
            cat > /etc/yum.repos.d/tailscale.repo <<EOF
[tailscale-stable]
name=Tailscale stable
baseurl=https://pkgs.tailscale.com/stable/rhel/\$releasever/\$basearch
enabled=1
type=rpm
repo_gpgcheck=1
gpgcheck=0
gpgkey=https://pkgs.tailscale.com/stable/rhel/\$releasever/repo.gpg
EOF
            
            log "Installing Tailscale..."
            if command -v dnf &>/dev/null; then
                dnf install -y tailscale
            else
                yum install -y tailscale
            fi
            
            # Enable and start service
            systemctl enable --now tailscaled
            ;;
            
        *)
            error "Unsupported OS: $OS
            
Please install Tailscale manually:
  https://tailscale.com/download"
            ;;
    esac
    
    # Verify installation
    if command -v tailscale &>/dev/null; then
        success "Tailscale installed successfully ($(tailscale version))"
    else
        error "Tailscale installation failed"
    fi
}

get_preauth_key() {
    log "Getting pre-authentication key from Headscale server..."
    
    info "You need to run this command on your K8s VM to generate a key:"
    echo ""
    echo "    kubectl exec -n headscale deployment/headscale -- \\"
    echo "      headscale --user ${HEADSCALE_USER} preauthkeys create --reusable --expiration 24h"
    echo ""
    
    read -p "Enter the pre-auth key: " PREAUTH_KEY
    
    if [ -z "$PREAUTH_KEY" ]; then
        error "Pre-auth key cannot be empty"
    fi
    
    # Trim whitespace
    PREAUTH_KEY=$(echo "$PREAUTH_KEY" | xargs)
    
    success "Pre-auth key received"
}

connect_to_headscale() {
    log "Connecting to Headscale VPN network..."
    
    # Check if already connected
    if tailscale status --json 2>/dev/null | grep -q '"BackendState":"Running"'; then
        warn "Already connected to a Tailscale/Headscale network"
        
        info "Current status:"
        tailscale status
        
        read -p "Do you want to disconnect and reconnect? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            info "Keeping existing connection"
            return 0
        fi
        
        log "Disconnecting..."
        tailscale down
        sleep 2
    fi
    
    # Connect to Headscale
    log "Joining Headscale network at https://${HEADSCALE_SERVER}"
    
    if tailscale up \
        --login-server="https://${HEADSCALE_SERVER}" \
        --authkey="${PREAUTH_KEY}" \
        --accept-routes \
        --hostname="${WORKER_HOSTNAME}" 2>&1 | tee /tmp/tailscale-up.log; then
        
        sleep 3
        success "Successfully connected to Headscale VPN"
    else
        error "Failed to connect to Headscale network. Check /tmp/tailscale-up.log for details"
    fi
}

get_vpn_info() {
    log "Getting VPN connection information..."
    
    VPN_IP=$(tailscale ip -4 2>/dev/null | head -1)
    VPN_IP6=$(tailscale ip -6 2>/dev/null | head -1)
    
    if [ -z "$VPN_IP" ]; then
        error "Failed to get VPN IP address"
    fi
    
    success "VPN connection established"
}

enable_ip_forwarding() {
    log "Enabling IP forwarding..."
    
    # Enable IP forwarding for potential subnet routing
    echo 'net.ipv4.ip_forward = 1' | tee /etc/sysctl.d/99-tailscale.conf >/dev/null
    echo 'net.ipv6.conf.all.forwarding = 1' | tee -a /etc/sysctl.d/99-tailscale.conf >/dev/null
    sysctl -p /etc/sysctl.d/99-tailscale.conf >/dev/null 2>&1
    
    success "IP forwarding enabled"
}

test_connectivity() {
    log "Testing connectivity to K8s cluster..."
    
    info "Enter your K8s VM's VPN IP to test connectivity:"
    read -p "K8s VM VPN IP (e.g., 100.64.0.5): " K8S_VPN_IP
    
    if [ -z "$K8S_VPN_IP" ]; then
        warn "Skipping connectivity test"
        return 0
    fi
    
    # Test ping
    if ping -c 3 -W 2 "$K8S_VPN_IP" > /dev/null 2>&1; then
        success "Can reach K8s VM at $K8S_VPN_IP via VPN"
    else
        warn "Cannot ping K8s VM at $K8S_VPN_IP - this may be normal if ICMP is blocked"
    fi
    
    # Test PostgreSQL port
    read -p "Test PostgreSQL port? (Y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        if nc -zv "$K8S_VPN_IP" 30432 2>&1 | grep -q succeeded; then
            success "PostgreSQL port (30432) is accessible"
        else
            warn "Cannot reach PostgreSQL port (30432) - ensure NodePort service is created"
        fi
    fi
}

show_summary() {
    echo ""
    echo "==========================================="
    success "GPU Worker Connected to Headscale VPN!"
    echo "==========================================="
    echo ""
    echo "🌐 VPN Connection"
    echo "  Server:          https://${HEADSCALE_SERVER}"
    echo "  Hostname:        ${WORKER_HOSTNAME}"
    echo "  User:            ${HEADSCALE_USER}"
    echo "  IPv4:            ${VPN_IP}"
    if [ -n "$VPN_IP6" ]; then
        echo "  IPv6:            ${VPN_IP6}"
    fi
    echo ""
    echo "📊 Useful Commands"
    echo "  Check status:    tailscale status"
    echo "  Check IP:        tailscale ip"
    echo "  View peers:      tailscale status"
    echo "  Disconnect:      sudo tailscale down"
    echo "  Reconnect:       sudo tailscale up --login-server=https://${HEADSCALE_SERVER}"
    echo ""
    echo "🔗 Database Connection (from june-tts)"
    echo "  Set these environment variables:"
    echo "    DB_HOST=<K8s_VM_VPN_IP>      # e.g., 100.64.0.5"
    echo "    DB_PORT=30432"
    echo "    DB_NAME=keycloak             # or june"
    echo "    DB_USER=keycloak"
    echo "    DB_PASSWORD=<your_password>"
    echo ""
    echo "📋 Next Steps"
    echo "  1. Update june-tts environment variables with K8s VM's VPN IP"
    echo "  2. Restart june-tts service"
    echo "  3. Check june-tts logs for database connectivity"
    echo ""
}

# Main execution
main() {
    check_headscale_server
    install_tailscale
    get_preauth_key
    connect_to_headscale
    get_vpn_info
    enable_ip_forwarding
    test_connectivity
    show_summary
}

main "$@"
