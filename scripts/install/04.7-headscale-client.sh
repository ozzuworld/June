#!/bin/bash
# June Platform - Phase 4.7: Headscale Client Setup
# Install Tailscale client on the K8s node and connect to Headscale VPN

set -e

source "$(dirname "$0")/../common/logging.sh"
source "$(dirname "$0")/../common/validation.sh"

ROOT_DIR="${1:-$(dirname $(dirname $(dirname $0)))}"

# Source configuration
CONFIG_FILE="${ROOT_DIR}/config.env"
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
fi

# Default values
HEADSCALE_NAMESPACE="${HEADSCALE_NAMESPACE:-headscale}"
HEADSCALE_USER="${HEADSCALE_USER:-k8s-node}"

header "Setting Up Headscale VPN Client"

# Validate required variables
if [ -z "$DOMAIN" ]; then
    error "DOMAIN is not set in config.env"
fi

check_headscale_ready() {
    log "Checking if Headscale server is ready..."
    
    if ! kubectl get deployment headscale -n "$HEADSCALE_NAMESPACE" &>/dev/null; then
        error "Headscale deployment not found. Please run phase 04.6-headscale first."
    fi
    
    if ! kubectl wait --for=condition=available deployment/headscale -n "$HEADSCALE_NAMESPACE" --timeout=10s &>/dev/null; then
        error "Headscale is not ready. Please wait for it to start."
    fi
    
    success "Headscale server is ready"
}

install_tailscale() {
    log "Installing Tailscale client..."
    
    # Check if tailscale is already installed
    if command -v tailscale &>/dev/null; then
        success "Tailscale already installed"
        return 0
    fi
    
    # Install Tailscale for Ubuntu 24.04
    log "Adding Tailscale repository..."
    curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg | tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
    curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list | tee /etc/apt/sources.list.d/tailscale.list
    
    log "Updating package list..."
    apt-get update -qq
    
    log "Installing Tailscale..."
    apt-get install -y tailscale -qq
    
    success "Tailscale installed successfully"
}

create_headscale_user() {
    log "Creating Headscale user: $HEADSCALE_USER"
    
    # Try to create user (ignore if already exists)
    kubectl exec -n "$HEADSCALE_NAMESPACE" deployment/headscale -- \
        headscale users create "$HEADSCALE_USER" 2>/dev/null || true
    
    # Verify user exists
    if kubectl exec -n "$HEADSCALE_NAMESPACE" deployment/headscale -- \
        headscale users list | grep -q "$HEADSCALE_USER"; then
        success "User $HEADSCALE_USER ready"
    else
        error "Failed to create user $HEADSCALE_USER"
    fi
}

generate_preauth_key() {
    log "Generating pre-authentication key..."
    
    # Generate a non-reusable key valid for 1 hour (enough for setup)
    PREAUTH_KEY=$(kubectl exec -n "$HEADSCALE_NAMESPACE" deployment/headscale -- \
        headscale --user "$HEADSCALE_USER" preauthkeys create --expiration 1h 2>/dev/null | tail -1 | tr -d '\r\n')
    
    if [ -z "$PREAUTH_KEY" ]; then
        error "Failed to generate pre-authentication key"
    fi
    
    success "Pre-authentication key generated"
}

join_headscale_network() {
    log "Connecting to Headscale VPN network..."
    
    # Check if already connected
    if tailscale status --json 2>/dev/null | grep -q '"BackendState":"Running"'; then
        warn "Already connected to Tailscale/Headscale network"
        
        # Show current status
        info "Current VPN status:"
        tailscale status
        return 0
    fi
    
    # Connect to Headscale
    log "Joining network with server: https://headscale.${DOMAIN}"
    tailscale up \
        --login-server="https://headscale.${DOMAIN}" \
        --authkey="$PREAUTH_KEY" \
        --accept-routes \
        --advertise-tags="tag:k8s-node" \
        --hostname="$(hostname)" 2>/dev/null || \
        error "Failed to connect to Headscale network"
    
    # Wait a moment for connection to establish
    sleep 3
    
    success "Successfully joined Headscale VPN network"
}

get_vpn_ip() {
    log "Getting VPN IP address..."
    
    VPN_IP=$(tailscale ip -4 2>/dev/null | head -1)
    
    if [ -z "$VPN_IP" ]; then
        error "Failed to get VPN IP address"
    fi
    
    success "VPN IP: $VPN_IP"
}

enable_ip_forwarding() {
    log "Enabling IP forwarding for subnet routing..."
    
    # Enable IP forwarding
    echo 'net.ipv4.ip_forward = 1' | tee /etc/sysctl.d/99-tailscale.conf >/dev/null
    echo 'net.ipv6.conf.all.forwarding = 1' | tee -a /etc/sysctl.d/99-tailscale.conf >/dev/null
    sysctl -p /etc/sysctl.d/99-tailscale.conf >/dev/null 2>&1
    
    success "IP forwarding enabled"
}

register_node_in_headscale() {
    log "Verifying node registration in Headscale..."
    
    # Wait a moment for node to appear
    sleep 2
    
    # Get node list and check if this node is registered
    NODE_LIST=$(kubectl exec -n "$HEADSCALE_NAMESPACE" deployment/headscale -- \
        headscale nodes list 2>/dev/null)
    
    if echo "$NODE_LIST" | grep -q "$(hostname)"; then
        success "Node successfully registered in Headscale"
    else
        warn "Node may not be fully registered yet. Check with: kubectl exec -n $HEADSCALE_NAMESPACE deployment/headscale -- headscale nodes list"
    fi
}

show_summary() {
    header "Headscale Client Setup Complete"
    
    echo "🌐 VPN Connection"
    echo "  Server:          https://headscale.${DOMAIN}"
    echo "  VPN IP:          $VPN_IP"
    echo "  Hostname:        $(hostname)"
    echo "  User:            $HEADSCALE_USER"
    echo ""
    echo "📊 Status"
    echo "  Check status:    tailscale status"
    echo "  Check IP:        tailscale ip"
    echo "  Check routes:    ip route | grep 100.64"
    echo ""
    echo "🔗 Access K8s Services from VPN"
    echo "  Use this IP from any VPN-connected device: $VPN_IP"
    echo ""
    echo "  Example (after exposing services via NodePort):"
    echo "    PostgreSQL:    psql postgresql://user:pass@${VPN_IP}:30432/db"
    echo "    Redis:         redis-cli -h ${VPN_IP} -p 30379"
    echo ""
    echo "📋 Useful Commands"
    echo "  Disconnect:      sudo tailscale down"
    echo "  Reconnect:       sudo tailscale up --login-server=https://headscale.${DOMAIN}"
    echo "  View peers:      tailscale status"
    echo "  List nodes:      kubectl exec -n ${HEADSCALE_NAMESPACE} deployment/headscale -- headscale nodes list"
    echo ""
}

# Main installation flow
main() {
    check_headscale_ready
    install_tailscale
    create_headscale_user
    generate_preauth_key
    join_headscale_network
    get_vpn_ip
    enable_ip_forwarding
    register_node_in_headscale
    show_summary
}

main
