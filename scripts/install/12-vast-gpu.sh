#!/bin/bash
# Phase 12: Deploy Vast.ai Virtual Kubelet Provider
# Enables remote GPU resources from Vast.ai in the Kubernetes cluster

set -e

source "$(dirname "$0")/../common/common.sh"

ROOT_DIR="$1"
if [ -z "$ROOT_DIR" ]; then
    error "Root directory not provided"
fi

log "Starting Vast.ai Virtual Kubelet Provider deployment..."

# Load configuration
source "$ROOT_DIR/config.env"

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    error "kubectl is not installed or not in PATH"
fi

# Check if cluster is accessible
if ! kubectl cluster-info &>/dev/null; then
    error "Cannot connect to Kubernetes cluster"
fi

# Check for Vast.ai API key
if [ -z "$VAST_API_KEY" ]; then
    warn "VAST_API_KEY not set in config.env"
    echo ""
    echo "🔑 To enable Vast.ai GPU provider, add your API key to config.env:"
    echo "   VAST_API_KEY=vast_api_key_your_actual_key_here"
    echo ""
    echo "Get your API key from: https://console.vast.ai/"
    echo "   1. Login to console.vast.ai"
    echo "   2. Go to Account → API Keys"
    echo "   3. Create New API Key"
    echo "   4. Add VAST_API_KEY=your_key to config.env"
    echo ""
    warn "Skipping Vast.ai provider deployment (no API key)"
    exit 0
fi

log "Vast.ai API key detected, proceeding with deployment..."

# Set default Vast.ai configuration if not specified
export VAST_GPU_TYPE="${VAST_GPU_TYPE:-RTX3060}"
export VAST_MAX_PRICE_PER_HOUR="${VAST_MAX_PRICE_PER_HOUR:-0.50}"
export VAST_MIN_GPU_MEMORY="${VAST_MIN_GPU_MEMORY:-12}"
export VAST_RELIABILITY_SCORE="${VAST_RELIABILITY_SCORE:-0.95}"
export VAST_MIN_DOWNLOAD_SPEED="${VAST_MIN_DOWNLOAD_SPEED:-100}"
export VAST_MIN_UPLOAD_SPEED="${VAST_MIN_UPLOAD_SPEED:-100}"
export VAST_DATACENTER_LOCATION="${VAST_DATACENTER_LOCATION:-US}"
export VAST_PREFERRED_REGIONS="${VAST_PREFERRED_REGIONS:-US-CA,US-TX,US-NY,US}"
export VAST_VERIFIED_ONLY="${VAST_VERIFIED_ONLY:-true}"
export VAST_RENTABLE_ONLY="${VAST_RENTABLE_ONLY:-true}"

log "Vast.ai Configuration:"
echo "  GPU Type: $VAST_GPU_TYPE"
echo "  Max Price: \$$VAST_MAX_PRICE_PER_HOUR/hour"
echo "  Min GPU Memory: ${VAST_MIN_GPU_MEMORY}GB"
echo "  Reliability: ${VAST_RELIABILITY_SCORE}+"
echo "  Location: $VAST_DATACENTER_LOCATION"
echo "  Preferred Regions: $VAST_PREFERRED_REGIONS"

# Create temporary files for processing
TEMP_SECRETS=$(mktemp)
TEMP_CONFIG=$(mktemp)
TEMP_DEPLOYMENT=$(mktemp)
trap "rm -f $TEMP_SECRETS $TEMP_CONFIG $TEMP_DEPLOYMENT" EXIT

# Process secrets template with proper validation
log "Creating Vast.ai secrets..."
if [ ! -f "$ROOT_DIR/k8s/vast-gpu/secrets-template.yaml" ]; then
    error "Secrets template not found: $ROOT_DIR/k8s/vast-gpu/secrets-template.yaml"
fi

# Validate API key format
if [[ ! "$VAST_API_KEY" =~ ^[a-f0-9]{64}$ ]] && [[ ! "$VAST_API_KEY" =~ ^vast_api_key_ ]]; then
    warn "VAST_API_KEY format appears invalid (should be 64-char hex or start with 'vast_api_key_')"
fi

# Process secrets with variable substitution
log "Substituting variables in secrets template..."
cat "$ROOT_DIR/k8s/vast-gpu/secrets-template.yaml" | \
    sed "s/YOUR_VAST_API_KEY_HERE/$VAST_API_KEY/g" | \
    sed "s/YOUR_GEMINI_API_KEY_HERE/${GEMINI_API_KEY:-changeme}/g" > "$TEMP_SECRETS"

# Validate the processed secrets file
if ! kubectl apply --dry-run=client -f "$TEMP_SECRETS" &>/dev/null; then
    error "Generated secrets file is invalid. Check your API keys for special characters."
fi

# Process provider config with environment substitution
log "Configuring Vast.ai provider settings..."
if [ -f "$ROOT_DIR/k8s/vast-gpu/vast-provider-config.yaml" ]; then
    envsubst < "$ROOT_DIR/k8s/vast-gpu/vast-provider-config.yaml" > "$TEMP_CONFIG"
else
    warn "Provider config not found, using default configuration"
fi

# Process virtual kubelet deployment
log "Preparing Virtual Kubelet deployment..."
cp "$ROOT_DIR/k8s/vast-gpu/virtual-kubelet-deployment.yaml" "$TEMP_DEPLOYMENT"

# Apply RBAC first
log "Setting up RBAC permissions..."
if kubectl apply -f "$ROOT_DIR/k8s/vast-gpu/rbac.yaml"; then
    success "RBAC permissions applied"
else
    error "Failed to apply RBAC permissions"
fi

# Apply secrets with better error handling
log "Creating API key secrets..."
if kubectl apply -f "$TEMP_SECRETS"; then
    success "Secrets created successfully"
else
    error "Failed to create secrets. Check the secrets template and API key format."
fi

# Apply provider configuration
if [ -f "$TEMP_CONFIG" ] && [ -s "$TEMP_CONFIG" ]; then
    log "Installing Vast.ai provider configuration..."
    kubectl apply -f "$TEMP_CONFIG"
fi

# Apply Virtual Kubelet deployment
log "Deploying Virtual Kubelet with Vast.ai provider..."
kubectl apply -f "$TEMP_DEPLOYMENT"

# Apply services
log "Creating Vast.ai GPU services..."
if [ -f "$ROOT_DIR/k8s/vast-gpu/services.yaml" ]; then
    kubectl apply -f "$ROOT_DIR/k8s/vast-gpu/services.yaml"
fi

# Wait for Virtual Kubelet to be ready
log "Waiting for Virtual Kubelet to be ready..."
if ! kubectl wait --for=condition=available --timeout=180s deployment/virtual-kubelet-vast -n kube-system; then
    warn "Virtual Kubelet not ready after 3 minutes, checking status..."
    kubectl get pods -n kube-system -l app=virtual-kubelet-vast
    kubectl describe deployment/virtual-kubelet-vast -n kube-system
    # Show logs for debugging
    echo ""
    log "Recent Virtual Kubelet logs:"
    kubectl logs -n kube-system deployment/virtual-kubelet-vast --tail=50 || true
fi

# Check for the virtual node
log "Checking for Vast.ai virtual node..."
VIRTUAL_NODE=""
for i in {1..30}; do
    VIRTUAL_NODE=$(kubectl get nodes -l type=virtual-kubelet -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [ -n "$VIRTUAL_NODE" ]; then
        success "Virtual node '$VIRTUAL_NODE' detected"
        break
    fi
    echo -n "."
    sleep 2
done
echo "" # New line after dots

if [ -z "$VIRTUAL_NODE" ]; then
    warn "Virtual node not detected yet, checking logs..."
    kubectl logs -n kube-system deployment/virtual-kubelet-vast --tail=20 || true
fi

# Apply GPU services deployment if virtual node is ready
if [ -n "$VIRTUAL_NODE" ] && [ -f "$ROOT_DIR/k8s/vast-gpu/gpu-services-deployment.yaml" ]; then
    log "Deploying GPU services to Vast.ai virtual node..."
    kubectl apply -f "$ROOT_DIR/k8s/vast-gpu/gpu-services-deployment.yaml"
else
    log "GPU services deployment will be applied when virtual node is available"
    echo "  Run: kubectl apply -f k8s/vast-gpu/gpu-services-deployment.yaml"
fi

# Show deployment status
echo ""
log "=== Vast.ai Provider Deployment Status ==="
echo ""
echo "📋 Virtual Kubelet Status:"
kubectl get deployment -n kube-system virtual-kubelet-vast || echo "Deployment not found"

echo ""
echo "🖥️ Virtual Nodes:"
kubectl get nodes -l type=virtual-kubelet -o wide || echo "No virtual nodes found yet"

echo ""
echo "🔌 GPU Services:"
kubectl get svc | grep "stt\|tts" || echo "GPU services not deployed yet"

echo ""
echo "📊 ConfigMap:"
kubectl get configmap vast-provider-config -n kube-system || echo "ConfigMap not found"

echo ""
echo "🔐 Secrets:"
kubectl get secret vast-api-secret -n kube-system || echo "Secret not found"

echo ""
log "=== Vast.ai Management Commands ==="
echo ""
echo "# View Virtual Kubelet logs:"
echo "kubectl logs -n kube-system deployment/virtual-kubelet-vast -f"
echo ""
echo "# Check virtual nodes:"
echo "kubectl get nodes -l type=virtual-kubelet"
echo ""
echo "# Monitor GPU pod scheduling:"
echo "kubectl get pods -o wide | grep vast-gpu"
echo ""
echo "# Check Vast.ai instance status:"
echo "kubectl logs -n kube-system deployment/virtual-kubelet-vast | grep 'VAST-NA'"
echo ""
echo "# Deploy GPU services manually (if not auto-deployed):"
echo "kubectl apply -f k8s/vast-gpu/gpu-services-deployment.yaml"

echo ""
success "Vast.ai Virtual Kubelet Provider deployment completed!"

echo ""
log "=== Configuration Summary ==="
echo "  API Integration: Vast.ai API connected"
echo "  GPU Selection: $VAST_GPU_TYPE with ${VAST_MIN_GPU_MEMORY}GB+ VRAM"
echo "  Budget: Max \$$VAST_MAX_PRICE_PER_HOUR/hour"
echo "  Geographic Preference: $VAST_DATACENTER_LOCATION ($VAST_PREFERRED_REGIONS)"
echo "  Quality Requirements: ${VAST_RELIABILITY_SCORE}+ reliability, ${VAST_MIN_DOWNLOAD_SPEED}+ Mbps"
if [ -n "$VIRTUAL_NODE" ]; then
    echo "  Virtual Node: $VIRTUAL_NODE (Ready)"
else
    echo "  Virtual Node: Initializing... (check logs)"
fi
echo ""
echo "🚀 GPU workloads will now automatically use Vast.ai resources when local GPUs are unavailable!"
echo ""