#!/bin/bash

# Headscale Sidecar Deployment Script
# This script automates the deployment of June services with Tailscale sidecars

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="june-services"
HEADSCALE_NAMESPACE="headscale"
HEADSCALE_SERVER="https://headscale.ozzu.world"

# Services to deploy
SERVICES=("june-orchestrator" "june-idp" "june-gpu-services" "livekit")

echo -e "${BLUE}🚀 Starting Headscale Sidecar Deployment${NC}"
echo "=========================================="

# Function to print status messages
print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check prerequisites
echo -e "${BLUE}📋 Checking prerequisites...${NC}"

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    print_error "kubectl is not installed or not in PATH"
    exit 1
fi

# Check if headscale namespace exists
if ! kubectl get namespace "$HEADSCALE_NAMESPACE" &> /dev/null; then
    print_error "Headscale namespace '$HEADSCALE_NAMESPACE' not found"
    print_warning "Please deploy Headscale first using: kubectl apply -f k8s/headscale/headscale-all.yaml"
    exit 1
fi

# Check if june-services namespace exists
if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
    print_warning "Creating namespace '$NAMESPACE'"
    kubectl create namespace "$NAMESPACE"
fi

print_status "Prerequisites check completed"

# Create headscale alias function (non-TTY to avoid control sequences)
headscale_cmd() {
    kubectl -n "$HEADSCALE_NAMESPACE" exec -i deployment/headscale -c headscale -- headscale "$@"
}

# Step 1: Create Headscale users
echo -e "\n${BLUE}👥 Creating Headscale users...${NC}"

for service in "${SERVICES[@]}"; do
    echo "Creating user: $service"
    if headscale_cmd users create "$service" 2>/dev/null; then
        print_status "Created user: $service"
    else
        print_warning "User $service may already exist"
    fi
done

# Step 2: Generate auth keys
echo -e "\n${BLUE}🔑 Generating authentication keys...${NC}"

AUTH_KEYS=""
for service in "${SERVICES[@]}"; do
    echo "Generating key for: $service"
    OUTPUT="$(headscale_cmd --user "$service" preauthkeys create --reusable --expiration 180d 2>&1 || true)"
    
    # Normalize output: remove CR, strip ANSI escape codes, remove control chars
    OUTPUT_CLEAN="$(printf "%s" "$OUTPUT" | tr -d '\r' | sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g' | sed 's/[[:cntrl:]]//g')"
    
    KEY=""
    
    # Method 1: Look for tskey-* format
    KEY="$(printf "%s" "$OUTPUT_CLEAN" | grep -oE 'tskey-[A-Za-z0-9-]+' | head -n1)"
    
    # Method 2: Look for 64-char hex (prefer last occurrence)
    if [ -z "$KEY" ]; then
        KEY="$(printf "%s" "$OUTPUT_CLEAN" | grep -oE '[0-9a-fA-F]{64}' | tail -n1)"
    fi
    
    # Method 3: JSON fallback if available
    if [ -z "$KEY" ]; then
        JSON_OUT="$(headscale_cmd --output json --user "$service" preauthkeys create --reusable --expiration 180d 2>/dev/null || true)"
        KEY="$(printf "%s" "$JSON_OUT" | grep -oE 'tskey-[A-Za-z0-9-]+' | head -n1)"
        if [ -z "$KEY" ]; then
            KEY="$(printf "%s" "$JSON_OUT" | grep -oE '[0-9a-fA-F]{64}' | head -n1)"
        fi
    fi

    if [ -n "$KEY" ] && [ ${#KEY} -ge 32 ]; then
        AUTH_KEYS="${AUTH_KEYS}  ${service}-authkey: \"${KEY}\"\n"
        print_status "Generated key for: $service (${KEY:0:8}...${KEY: -8})"
    else
        print_error "Failed to parse key for: $service"
        echo "Headscale output (raw):"
        echo "$OUTPUT"
        echo "Headscale output (clean):"
        echo "$OUTPUT_CLEAN"
        echo "Parsed key: '$KEY' (length: ${#KEY})"
        exit 1
    fi
done

# Step 3: Create Kubernetes secret
echo -e "\n${BLUE}🔐 Creating Kubernetes secret...${NC}"

cat > /tmp/headscale-auth-secrets.yaml << EOF
apiVersion: v1
kind: Secret
metadata:
  name: headscale-auth-keys
  namespace: $NAMESPACE
type: Opaque
stringData:
$(echo -e "$AUTH_KEYS")
EOF

kubectl apply -f /tmp/headscale-auth-secrets.yaml
print_status "Created Kubernetes secret with auth keys"

# Clean up temp file
rm -f /tmp/headscale-auth-secrets.yaml

# Step 4: Deploy services
echo -e "\n${BLUE}🚢 Deploying services with sidecars...${NC}"

# Deploy June Orchestrator
if [ -f "k8s/june-services/deployments/june-orchestrator-headscale.yaml" ]; then
    kubectl apply -f k8s/june-services/deployments/june-orchestrator-headscale.yaml
    print_status "Deployed June Orchestrator"
else
    print_warning "k8s/june-services/deployments/june-orchestrator-headscale.yaml not found, skipping"
fi

# Deploy June IDP
if [ -f "k8s/june-services/deployments/june-idp-headscale.yaml" ]; then
    kubectl apply -f k8s/june-services/deployments/june-idp-headscale.yaml
    print_status "Deployed June IDP"
else
    print_warning "k8s/june-services/deployments/june-idp-headscale.yaml not found, skipping"
fi

# Deploy GPU Services (updated existing file)
kubectl apply -f k8s/june-services/deployments/june-gpu-services.yaml
print_status "Deployed June GPU Services"

# Deploy LiveKit (if using Helm)
if [ -f "k8s/livekit/livekit-values-headscale.yaml" ] && command -v helm &> /dev/null; then
    if helm list -n "$NAMESPACE" | grep -q livekit; then
        helm upgrade livekit ./helm/livekit -n "$NAMESPACE" -f k8s/livekit/livekit-values-headscale.yaml
        print_status "Updated LiveKit deployment"
    else
        print_warning "LiveKit Helm release not found, please deploy manually"
    fi
else
    print_warning "Helm not available or k8s/livekit/livekit-values-headscale.yaml not found, skipping LiveKit"
fi

# Step 5: Wait for deployments
echo -e "\n${BLUE}⏳ Waiting for deployments to be ready...${NC}"

for service in june-orchestrator june-idp june-gpu-services; do
    echo "Waiting for $service..."
    if kubectl wait --for=condition=available deployment/"$service" -n "$NAMESPACE" --timeout=300s 2>/dev/null; then
        print_status "$service is ready"
    else
        print_warning "$service is taking longer than expected"
    fi
done

# Step 6: Verify registrations
echo -e "\n${BLUE}🔍 Verifying Headscale registrations...${NC}"

echo "Registered nodes:"
headscale_cmd nodes list

# Step 7: Display access information
echo -e "\n${GREEN}🎉 Deployment completed!${NC}"
echo "=========================================="
echo "Your services should now be accessible via Tailscale:"
echo ""
echo "• June Orchestrator: https://june-orchestrator.tail.ozzu.world"
echo "• June IDP (Keycloak): https://june-idp.tail.ozzu.world"  
echo "• LiveKit: https://livekit.tail.ozzu.world"
echo "• TTS Service: https://june-tts.tail.ozzu.world"
echo "• STT Service: https://june-stt.tail.ozzu.world"
echo ""
echo "To check pod status:"
echo "kubectl get pods -n $NAMESPACE"
echo ""
echo "To check sidecar logs:"
echo "kubectl logs -n $NAMESPACE deployment/SERVICE_NAME -c tailscale"
echo ""
echo "To check Headscale status:"
echo "kubectl -n $HEADSCALE_NAMESPACE exec -it deployment/headscale -c headscale -- headscale nodes list"

print_status "Headscale sidecar deployment completed successfully!"