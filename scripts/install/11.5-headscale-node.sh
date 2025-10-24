#!/bin/bash
# Phase 11.5 - Headscale Node Subnet Router (FINAL ROBUST VERSION)
# Connects this Kubernetes node to existing Headscale server as subnet router
# - Installs Tailscale on the K8s node
# - Connects to Headscale with preauth key
# - Advertises Kubernetes Service/Pod routes
# - Approves ALL routes for this node automatically
# 
# IMPORTANT: This phase assumes Headscale server is already installed and running
# in your cluster (from an earlier phase). It does NOT install Headscale itself.

set -euo pipefail

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
log(){ echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $*"; }
success(){ echo -e "${GREEN}✅${NC} $*"; }
warn(){ echo -e "${YELLOW}⚠️${NC} $*"; }
error(){ echo -e "${RED}❌${NC} $*"; exit 1; }

ROOT_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)}"
CONFIG_FILE="${CONFIG_FILE:-${ROOT_DIR}/config.env}"
[ -f "$CONFIG_FILE" ] || error "config.env not found at $CONFIG_FILE"
source "$CONFIG_FILE"

# Required configuration variables
: "${HEADSCALE_DOMAIN:?Set HEADSCALE_DOMAIN in config.env, e.g. headscale.ozzu.world}"
: "${HEADSCALE_NAMESPACE:=headscale}"
: "${HEADSCALE_USER:=ozzu}"

# Auto-detect Kubernetes network CIDRs with fallback to config
detect_k8s_cidrs() {
    local service_cidr=""
    local pod_cidr=""
    
    # Try to detect Service CIDR from kube-apiserver
    if [ -f /etc/kubernetes/manifests/kube-apiserver.yaml ]; then
        service_cidr=$(grep -o 'service-cluster-ip-range=[^[:space:]]*' /etc/kubernetes/manifests/kube-apiserver.yaml 2>/dev/null | cut -d= -f2 || echo "")
    fi
    
    # Try to detect Pod CIDR from nodes or Flannel config
    if command -v kubectl >/dev/null 2>&1; then
        pod_cidr=$(kubectl get nodes -o jsonpath='{.items[0].spec.podCIDR}' 2>/dev/null || echo "")
        
        # Fallback: try Flannel configmap
        if [ -z "$pod_cidr" ]; then
            pod_cidr=$(kubectl -n kube-flannel get cm kube-flannel-cfg -o jsonpath='{.data.net-conf\.json}' 2>/dev/null | grep -o '"Network":"[^"]*"' | cut -d'"' -f4 || echo "")
        fi
    fi
    
    # Use detected values or fallback to config
    K8S_SERVICE_CIDR="${service_cidr:-${K8S_SERVICE_CIDR:-10.96.0.0/12}}"
    K8S_POD_CIDR="${pod_cidr:-${K8S_POD_CIDR:-10.244.0.0/16}}"
    
    log "Kubernetes network CIDRs: Services=${K8S_SERVICE_CIDR}, Pods=${K8S_POD_CIDR}"
}

HEADSCALE_URL="https://${HEADSCALE_DOMAIN}"

log "Phase 11.5: Configuring node as Headscale subnet router"

# Verify Headscale server is running
log "Verifying Headscale deployment exists in namespace: ${HEADSCALE_NAMESPACE}"
if ! kubectl get deploy -n "$HEADSCALE_NAMESPACE" headscale >/dev/null 2>&1; then
  error "Headscale deployment not found in namespace ${HEADSCALE_NAMESPACE}
  
Make sure Headscale server is installed first. This phase only connects
the node to an existing Headscale server, it does not install Headscale itself."
fi

# Auto-detect network CIDRs
detect_k8s_cidrs

log "Installing Tailscale on this node (system service)"
if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sh
    systemctl enable --now tailscaled
    success "Tailscale installed and started"
else
    log "Tailscale already installed"
    systemctl enable --now tailscaled 2>/dev/null || true
fi

log "Enabling IP forwarding and performance tuning"
cat >/etc/sysctl.d/99-tailscale.conf <<EOF
# Tailscale subnet router configuration
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
EOF
sysctl --system >/dev/null 2>&1 || true

# Best-effort UDP GRO forwarding optimization
PRIMARY_NIC=$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')
if [ -n "${PRIMARY_NIC}" ] && command -v ethtool >/dev/null 2>&1; then
  log "Enabling UDP GRO forwarding on ${PRIMARY_NIC}"
  ethtool -K "$PRIMARY_NIC" rx-udp-gro-forwarding on 2>/dev/null || warn "Could not enable UDP GRO forwarding"
fi

log "Ensuring Headscale user exists: ${HEADSCALE_USER}"
if ! kubectl -n "$HEADSCALE_NAMESPACE" exec deploy/headscale -- headscale users list | awk 'NR>1 {print $3}' | grep -qx "$HEADSCALE_USER"; then
  kubectl -n "$HEADSCALE_NAMESPACE" exec deploy/headscale -- headscale users create "$HEADSCALE_USER" >/dev/null
  success "Created Headscale user: ${HEADSCALE_USER}"
else
  log "Headscale user already exists: ${HEADSCALE_USER}"
fi

log "Generating preauth key (reusable, 24h expiration)"
PREAUTH=$(kubectl -n "$HEADSCALE_NAMESPACE" exec deploy/headscale -- headscale preauthkeys create --user "$HEADSCALE_USER" --expiration 24h --reusable 2>/dev/null | tail -n1 | tr -d '\r\n')
[ -n "$PREAUTH" ] || error "Failed to obtain preauth key from Headscale"
success "Generated preauth key: ${PREAUTH:0:8}..."

log "Connecting node to Headscale with subnet routes"
# Clean slate: logout if already connected
if tailscale status >/dev/null 2>&1; then
  tailscale logout >/dev/null 2>&1 || true
  sleep 2
fi

# Connect with subnet routing
if ! tailscale up \
  --login-server="$HEADSCALE_URL" \
  --authkey="$PREAUTH" \
  --advertise-routes="$K8S_SERVICE_CIDR,$K8S_POD_CIDR" \
  --accept-routes; then
  error "Failed to connect to Headscale at $HEADSCALE_URL"
fi

success "Node connected to Headscale network"
log "Waiting for routes to propagate..."
sleep 5

# SIMPLIFIED APPROACH: Enable ALL routes for this node
NODE_NAME=$(hostname)
log "Enabling ALL routes for node '$NODE_NAME'"

# Get all route IDs for this node (regardless of CIDR)
ROUTE_IDS=$(kubectl -n "$HEADSCALE_NAMESPACE" exec deploy/headscale -- headscale routes list 2>/dev/null \
  | awk -v n="$NODE_NAME" 'NR>1 && $2==n && $4=="true" && $5=="false" {print $1}' \
  | tr '\n' ' ')

if [ -z "$ROUTE_IDS" ]; then
  warn "No unapproved routes found for node '$NODE_NAME'. Current routes:"
  kubectl -n "$HEADSCALE_NAMESPACE" exec deploy/headscale -- headscale routes list || true
  log "Routes may already be enabled or node not found."
else
  log "Enabling route IDs: $ROUTE_IDS"
  
  # Enable each route ID
  for ROUTE_ID in $ROUTE_IDS; do
    kubectl -n "$HEADSCALE_NAMESPACE" exec deploy/headscale -- headscale routes enable --route "$ROUTE_ID" >/dev/null 2>&1 || warn "Failed to enable route $ROUTE_ID"
    log "Enabled route ID: $ROUTE_ID"
  done
fi

# Verify all routes for this node are enabled
sleep 2
ENABLED_COUNT=$(kubectl -n "$HEADSCALE_NAMESPACE" exec deploy/headscale -- headscale routes list 2>/dev/null \
  | awk -v n="$NODE_NAME" 'NR>1 && $2==n && $5=="true" {count++} END {print count+0}')

TOTAL_COUNT=$(kubectl -n "$HEADSCALE_NAMESPACE" exec deploy/headscale -- headscale routes list 2>/dev/null \
  | awk -v n="$NODE_NAME" 'NR>1 && $2==n {count++} END {print count+0}')

if [ "$ENABLED_COUNT" -gt 0 ] && [ "$ENABLED_COUNT" -eq "$TOTAL_COUNT" ]; then
  success "All $ENABLED_COUNT routes enabled for node '$NODE_NAME'"
elif [ "$ENABLED_COUNT" -gt 0 ]; then
  success "$ENABLED_COUNT/$TOTAL_COUNT routes enabled for node '$NODE_NAME'"
else
  warn "No routes appear to be enabled. Manual approval may be needed."
fi

log "Current Tailscale status:"
tailscale status || warn "Failed to get Tailscale status"

log "Final Headscale routes status:"
kubectl -n "$HEADSCALE_NAMESPACE" exec deploy/headscale -- headscale routes list 2>/dev/null || warn "Failed to list Headscale routes"

success "Phase 11.5 complete: Node configured as Headscale subnet router"
log ""
log "Your Kubernetes node is now advertising networks to Headscale."
log "Routes enabled: $ENABLED_COUNT/$TOTAL_COUNT"
log ""
log "External devices connected to the same Headscale network can now"
log "directly access Kubernetes services at their ClusterIP addresses."
log ""
log "🎯 TEST CONNECTIVITY FROM GPU CONTAINER:"
log "  tailscale status"
log "  curl http://10.104.215.160:8080/healthz"