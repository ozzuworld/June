#!/bin/bash

# Headscale Sidecar Deployment Script
# This script automates the deployment of June services with Tailscale sidecars
# Updated to work with the actual Helm-based architecture

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

# Services to deploy with sidecars
SERVICES=("june-orchestrator" "june-idp")

# Get script directory for relative path resolution
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}🚀 Starting Headscale Sidecar Deployment${NC}"
echo "==========================================="
echo "Root directory: $ROOT_DIR"
echo "Helm chart: $ROOT_DIR/helm/june-platform"

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

# Check if jq is available (required for JSON parsing)
if ! command -v jq &> /dev/null; then
    print_error "jq is required but not installed. Please install jq and rerun."
    exit 1
fi

# Check if helm is available
if ! command -v helm &> /dev/null; then
    print_error "helm is required but not installed. Please install helm and rerun."
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

# Check if Helm chart exists
if [ ! -d "$ROOT_DIR/helm/june-platform" ]; then
    print_error "Helm chart not found at: $ROOT_DIR/helm/june-platform"
    print_warning "Please ensure you're running this script from the June repository root"
    exit 1
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

# Step 2: Generate auth keys via JSON output only
echo -e "\n${BLUE}🔑 Generating authentication keys...${NC}"

AUTH_KEYS=""
for service in "${SERVICES[@]}"; do
    echo "Generating key for: $service"
    OUTPUT_JSON="$(headscale_cmd --output json --user "$service" preauthkeys create --reusable --expiration 180d 2>/dev/null || true)"

    # Simplified key extraction
    KEY="$(printf "%s" "$OUTPUT_JSON" | jq -r '.key // .authKey // .auth_key // empty' 2>/dev/null | head -n1)"

    if [ -n "$KEY" ] && [ ${#KEY} -ge 32 ]; then
        AUTH_KEYS="${AUTH_KEYS}  ${service}-authkey: \"${KEY}\"\n"
        print_status "Generated key for: $service (${KEY:0:8}...${KEY: -8})"
    else
        print_error "Failed to parse key for: $service"
        echo "JSON response was:"
        echo "$OUTPUT_JSON"
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

# Step 4: Deploy services with sidecars using Helm
echo -e "\n${BLUE}🚢 Deploying services with Tailscale sidecars...${NC}"

# Check if june-platform release exists
if helm list -n "$NAMESPACE" | grep -q "june-platform"; then
    print_status "Upgrading existing june-platform release with Tailscale sidecars"
    HELM_COMMAND="upgrade"
else
    print_status "Installing june-platform release with Tailscale sidecars"
    HELM_COMMAND="install"
fi

# Deploy using Helm with Tailscale values
helm $HELM_COMMAND june-platform "$ROOT_DIR/helm/june-platform" \
    --namespace "$NAMESPACE" \
    --create-namespace \
    -f "$ROOT_DIR/helm/june-platform/values-headscale.yaml" \
    --timeout 15m

print_status "June Platform deployed with Tailscale sidecars"

# Step 5: Wait for deployments
echo -e "\n${BLUE}⏳ Waiting for deployments to be ready...${NC}"

for service in "${SERVICES[@]}"; do
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
# Use non-interactive mode for automation
kubectl -n "$HEADSCALE_NAMESPACE" exec deployment/headscale -c headscale -- headscale nodes list

# Step 7: Display access information
echo -e "\n${GREEN}🎉 Deployment completed!${NC}"
echo "==========================================="
echo "Your services should now be accessible via Tailscale:"
echo ""
echo "• June Orchestrator: https://june-orchestrator.tail.ozzu.world"
echo "• June IDP (Keycloak): https://june-idp.tail.ozzu.world"  
echo ""
echo "Standard access (unchanged):"
echo "• API: https://api.ozzu.world"
echo "• Identity: https://idp.ozzu.world"
echo ""
echo "To check pod status:"
echo "kubectl get pods -n $NAMESPACE"
echo ""
echo "To check sidecar logs:"
echo "kubectl logs -n $NAMESPACE deployment/SERVICE_NAME -c tailscale"
echo ""
echo "To check Headscale status:"
echo "kubectl -n $HEADSCALE_NAMESPACE exec -it deployment/headscale -c headscale -- headscale nodes list"
echo ""
echo "To disable Tailscale sidecars:"
echo "helm upgrade june-platform $ROOT_DIR/helm/june-platform --namespace $NAMESPACE --set tailscale.enabled=false"

print_status "Headscale sidecar deployment completed successfully!"