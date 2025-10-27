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

# Services to deploy with sidecars (now includes LiveKit)
SERVICES=("june-orchestrator" "june-idp" "livekit")

# Get script directory for relative path resolution
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}🚀 Starting Headscale Sidecar Deployment${NC}"
echo "==========================================="
echo "Root directory: $ROOT_DIR"
echo "Helm chart: $ROOT_DIR/helm/june-platform"

# Source configuration from environment or config file
if [ -f "${ROOT_DIR}/config.env" ]; then
    source "${ROOT_DIR}/config.env"
    echo -e "${GREEN}✅ Loaded configuration from ${ROOT_DIR}/config.env${NC}"
else
    echo -e "${RED}❌ Configuration file not found at ${ROOT_DIR}/config.env${NC}"
    echo -e "${YELLOW}⚠️  Please ensure config.env exists with required variables${NC}"
    exit 1
fi

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

# Validate required environment variables
validate_environment() {
    echo -e "${BLUE}🔍 Validating environment variables...${NC}"
    
    local required_vars=(
        "DOMAIN"
        "LETSENCRYPT_EMAIL"
        "GEMINI_API_KEY"
        "CLOUDFLARE_TOKEN"
    )
    
    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ]; then
            print_error "Required environment variable $var is not set"
            echo "Please check your config.env file"
            exit 1
        fi
    done
    
    print_status "Environment variables validated"
}

# Check prerequisites
echo -e "${BLUE}📋 Checking prerequisites...${NC}"

# Validate environment first
validate_environment

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

# Step X: Reconcile LiveKit ownership to june-platform
echo -e "\n${BLUE}🧹 Reconciling LiveKit resources ownership...${NC}"

# Detect a separate Helm release that owns LiveKit
LIVEKIT_RELEASES="$(helm list -A -o json | jq -r '.[] | select(.name|test("^livekit$")) | "\(.namespace):\(.name)"')"

if [ -n "$LIVEKIT_RELEASES" ]; then
  echo "Found standalone LiveKit Helm release(s):"
  echo "$LIVEKIT_RELEASES"
  while IFS= read -r rel; do
    rel_ns="$(echo "$rel" | cut -d: -f1)"
    rel_name="$(echo "$rel" | cut -d: -f2)"
    echo "Uninstalling release $rel_name in namespace $rel_ns..."
    helm uninstall "$rel_name" -n "$rel_ns" || true
  done <<< "$LIVEKIT_RELEASES"
fi

# Remove orphaned LiveKit resources that block june-platform ownership
echo "Deleting any orphaned LiveKit resources in namespace $NAMESPACE..."
kubectl delete deployment livekit-livekit-server -n "$NAMESPACE" --ignore-not-found
kubectl delete service livekit-livekit-server -n "$NAMESPACE" --ignore-not-found

# If still present with wrong Helm ownership, forcefully remove finalizers & delete
if kubectl get svc livekit-livekit-server -n "$NAMESPACE" &>/dev/null; then
  echo "Force-clearing finalizers on Service livekit-livekit-server..."
  kubectl patch service livekit-livekit-server -n "$NAMESPACE" \
    -p '{"metadata":{"finalizers":[]}}' --type=merge || true
  kubectl delete service livekit-livekit-server -n "$NAMESPACE" --force --grace-period=0 || true
fi

if kubectl get deploy livekit-livekit-server -n "$NAMESPACE" &>/dev/null; then
  echo "Force-clearing finalizers on Deployment livekit-livekit-server..."
  kubectl patch deployment livekit-livekit-server -n "$NAMESPACE" \
    -p '{"metadata":{"finalizers":[]}}' --type=merge || true
  kubectl delete deployment livekit-livekit-server -n "$NAMESPACE" --force --grace-period=0 || true
fi

# Ensure namespace is “owned” by Helm with june-platform labels (helps ownership)
kubectl label namespace "$NAMESPACE" app.kubernetes.io/managed-by=Helm --overwrite || true
kubectl annotate namespace "$NAMESPACE" meta.helm.sh/release-name=june-platform --overwrite || true
kubectl annotate namespace "$NAMESPACE" meta.helm.sh/release-namespace="$NAMESPACE" --overwrite || true

print_status "LiveKit ownership reconciled for june-platform"

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

# Deploy using Helm with Tailscale values and environment configuration
helm $HELM_COMMAND june-platform "$ROOT_DIR/helm/june-platform" \
    --namespace "$NAMESPACE" \
    --create-namespace \
    -f "$ROOT_DIR/helm/june-platform/values-headscale.yaml" \
    --set secrets.geminiApiKey="$GEMINI_API_KEY" \
    --set secrets.cloudflareToken="$CLOUDFLARE_TOKEN" \
    --set global.domain="$DOMAIN" \
    --set certificate.email="$LETSENCRYPT_EMAIL" \
    --set postgresql.password="${POSTGRESQL_PASSWORD:-Pokemon123!}" \
    --set keycloak.adminPassword="${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}" \
    --timeout 15m

print_status "June Platform deployed with Tailscale sidecars"

# Step 5: Wait for deployments
echo -e "\n${BLUE}⏳ Waiting for deployments to be ready...${NC}"

# Wait for core services
for service in "june-orchestrator" "june-idp"; do
    echo "Waiting for $service..."
    if kubectl wait --for=condition=available deployment/"$service" -n "$NAMESPACE" --timeout=300s 2>/dev/null; then
        print_status "$service is ready"
    else
        print_warning "$service is taking longer than expected"
    fi
done

# Wait for LiveKit (may have different naming)
echo "Waiting for LiveKit..."
if kubectl get deployment livekit-livekit-server -n "$NAMESPACE" &>/dev/null; then
    if kubectl wait --for=condition=available deployment/livekit-livekit-server -n "$NAMESPACE" --timeout=300s 2>/dev/null; then
        print_status "LiveKit is ready"
    else
        print_warning "LiveKit is taking longer than expected"
    fi
else
    print_warning "LiveKit deployment not found - it may be deployed separately"
fi

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
echo "• LiveKit: https://livekit.tail.ozzu.world"
echo ""
echo "Standard access (unchanged):"
echo "• API: https://api.ozzu.world"
echo "• Identity: https://idp.ozzu.world"
echo "• LiveKit: https://livekit.ozzu.world"
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