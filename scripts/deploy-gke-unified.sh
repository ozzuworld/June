#!/bin/bash
# scripts/deploy-gke-unified.sh - Deploy Harbor + June Services to GKE Autopilot

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

# Configuration
PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"
CLUSTER_NAME="${CLUSTER_NAME:-june-unified-cluster}"
DOMAIN="${DOMAIN:-api.yourdomain.com}"

log "🚀 Deploying Unified GKE Infrastructure"
log "📋 Project: $PROJECT_ID"
log "🌍 Region: $REGION"
log "🏗️ Cluster: $CLUSTER_NAME"

# Check prerequisites
command -v gcloud >/dev/null 2>&1 || error "gcloud CLI not found"
command -v terraform >/dev/null 2>&1 || error "terraform not found"
command -v helm >/dev/null 2>&1 || error "helm not found"
command -v kubectl >/dev/null 2>&1 || error "kubectl not found"

# Set project
gcloud config set project "$PROJECT_ID"

# Step 1: Deploy GKE infrastructure with Terraform
log "🏗️ Step 1: Deploying GKE Autopilot infrastructure..."
cd infra/gke

if [[ ! -f "terraform.tfstate" ]]; then
  terraform init
fi

terraform plan \
  -var="project_id=$PROJECT_ID" \
  -var="region=$REGION" \
  -var="cluster_name=$CLUSTER_NAME"

read -p "Deploy GKE infrastructure? (y/N): " -r
if [[ $REPLY =~ ^[Yy]$ ]]; then
  terraform apply \
    -var="project_id=$PROJECT_ID" \
    -var="region=$REGION" \
    -var="cluster_name=$CLUSTER_NAME" \
    -auto-approve
  success "GKE infrastructure deployed"
else
  warning "Infrastructure deployment skipped"
fi

# Get outputs from Terraform
POSTGRES_CONNECTION=$(terraform output -raw postgres_connection_name)
REDIS_HOST=$(terraform output -raw redis_host)
HARBOR_BUCKET=$(terraform output -raw harbor_registry_bucket)

cd ../..

# Step 2: Configure kubectl
log "🔧 Step 2: Configuring kubectl..."
gcloud container clusters get-credentials "$CLUSTER_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID"

success "kubectl configured for cluster: $CLUSTER_NAME"

# Step 3: Create secrets
log "🔐 Step 3: Creating Kubernetes secrets..."

# Create namespace if it doesn't exist
kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f -

# Get database passwords from Secret Manager
HARBOR_DB_PASSWORD=$(gcloud secrets versions access latest --secret="harbor-db-password" --project="$PROJECT_ID")
ORCHESTRATOR_DB_PASSWORD=$(gcloud secrets versions access latest --secret="june_orchestrator-db-password" --project="$PROJECT_ID")
IDP_DB_PASSWORD=$(gcloud secrets versions access latest --secret="june_idp-db-password" --project="$PROJECT_ID")

# Create application secrets
kubectl create secret generic june-secrets \
  --namespace=june-services \
  --from-literal=ORCHESTRATOR_CLIENT_ID="orchestrator-client" \
  --from-literal=ORCHESTRATOR_CLIENT_SECRET="orchestrator-secret-123" \
  --from-literal=STT_CLIENT_ID="stt-client" \
  --from-literal=STT_CLIENT_SECRET="stt-secret-123" \
  --from-literal=TTS_CLIENT_ID="tts-client" \
  --from-literal=TTS_CLIENT_SECRET="tts-secret-123" \
  --from-literal=GEMINI_API_KEY="${GEMINI_API_KEY:-}" \
  --from-literal=CHATTERBOX_API_KEY="${CHATTERBOX_API_KEY:-}" \
  --from-literal=KC_DB_PASSWORD="$IDP_DB_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -

success "Kubernetes secrets created"

# Step 4: Install Harbor
log "📦 Step 4: Installing Harbor registry..."

# Add Harbor Helm repository
helm repo add harbor https://helm.goharbor.io
helm repo update

# Create Harbor values with actual connection info
cat > /tmp/harbor-values.yaml << EOF
expose:
  type: loadBalancer
  loadBalancer:
    IP: ""
  tls:
    enabled: false  # We'll use ingress for SSL

externalURL: http://harbor.${CLUSTER_NAME}.svc.cluster.local

harborAdminPassword: "Harbor12345"

# Use external PostgreSQL
database:
  type: external
  external:
    host: "${POSTGRES_CONNECTION}"
    port: "5432"
    username: "harbor"
    password: "${HARBOR_DB_PASSWORD}"
    coreDatabase: "harbor"
    sslmode: "require"

# Use external Redis
redis:
  type: external
  external:
    addr: "${REDIS_HOST}:6379"

# Use Google Cloud Storage
registry:
  storage:
    gcs:
      bucket: "${HARBOR_BUCKET}"
      # We'll use Workload Identity instead of keyfile
      
# Resource limits for Autopilot
core:
  resources:
    requests:
      memory: 256Mi
      cpu: 100m
    limits:
      memory: 512Mi
      cpu: 500m

portal:
  resources:
    requests:
      memory: 128Mi
      cpu: 100m
    limits:
      memory: 256Mi
      cpu: 200m

jobservice:
  resources:
    requests:
      memory: 256Mi
      cpu: 100m
    limits:
      memory: 512Mi
      cpu: 500m

registry:
  controller:
    resources:
      requests:
        memory: 128Mi
        cpu: 100m
      limits:
        memory: 256Mi
        cpu: 200m

trivy:
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi

# Use Workload Identity
serviceAccount:
  create: false
  name: "harbor"
EOF

# Install Harbor
kubectl create namespace harbor --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install harbor harbor/harbor \
  --namespace harbor \
  --values /tmp/harbor-values.yaml \
  --timeout 15m \
  --wait

# Clean up values file
rm -f /tmp/harbor-values.yaml

success "Harbor installed successfully!"

# Step 5: Build and push images to Harbor
log "🐳 Step 5: Building and pushing images..."

# Get Harbor URL
HARBOR_URL="http://$(kubectl get service harbor -n harbor -o jsonpath='{.status.loadBalancer.ingress[0].ip}')"
if [[ "$HARBOR_URL" == "http://" ]]; then
  # Fallback to port-forward if LoadBalancer not ready
  warning "LoadBalancer not ready, using port-forward"
  kubectl port-forward -n harbor svc/harbor 8080:80 &
  PORT_FORWARD_PID=$!
  HARBOR_URL="http://localhost:8080"
  sleep 10
fi

log "Harbor URL: $HARBOR_URL"

# Login to Harbor (insecure for local development)
docker login $HARBOR_URL -u admin -p Harbor12345 --insecure

# Create Harbor project
curl -k -X POST "$HARBOR_URL/api/v2.0/projects" \
  -H "Content-Type: application/json" \
  -u "admin:Harbor12345" \
  -d '{"project_name":"june","public":true}' || true

# Build and push images
for SERVICE in june-orchestrator june-stt june-tts june-idp; do
  if [[ -d "June/services/$SERVICE" ]]; then
    SERVICE_PATH="June/services/$SERVICE"
  elif [[ -d "services/$SERVICE" ]]; then
    SERVICE_PATH="services/$SERVICE"
  else
    warning "Service path not found for $SERVICE, skipping"
    continue
  fi
  
  log "Building $SERVICE..."
  IMAGE_TAG="$HARBOR_URL/june/$SERVICE:latest"
  
  docker build -t "$IMAGE_TAG" "$SERVICE_PATH"
  docker push "$IMAGE_TAG"
  
  success "$SERVICE image pushed to Harbor"
done

# Kill port-forward if we started it
if [[ -n "${PORT_FORWARD_PID:-}" ]]; then
  kill $PORT_FORWARD_PID 2>/dev/null || true
fi

# Step 6: Deploy June services
log "🚀 Step 6: Deploying June services to Kubernetes..."

# Update K8s manifests with actual Harbor URL
HARBOR_REGISTRY_URL=$(echo $HARBOR_URL | sed 's|http://||')
sed -i "s|harbor.yourdomain.com|$HARBOR_REGISTRY_URL|g" k8s/june-services/*.yaml

# Update postgres connection in june-idp manifest
POSTGRES_HOST=$(echo $POSTGRES_CONNECTION | cut -d: -f1)
sed -i "s|POSTGRES_HOST|$POSTGRES_HOST|g" k8s/june-services/june-idp.yaml

# Apply manifests
kubectl apply -f k8s/june-services/

# Wait for deployments
log "⏳ Waiting for deployments to be ready..."
kubectl wait --namespace june-services \
  --for=condition=available deployment \
  --all \
  --timeout=600s

success "All June services deployed!"

# Step 7: Set up ingress
log "🌐 Step 7: Setting up external access..."

# Reserve static IP
gcloud compute addresses create june-services-ip --global --project="$PROJECT_ID" || true

# Get the static IP
STATIC_IP=$(gcloud compute addresses describe june-services-ip --global --project="$PROJECT_ID" --format="value(address)")

log "Static IP: $STATIC_IP"
log "Please configure DNS: $DOMAIN -> $STATIC_IP"

# Apply ingress with correct domain
sed -i "s|api.yourdomain.com|$DOMAIN|g" k8s/june-services/june-orchestrator.yaml
kubectl apply -f k8s/june-services/june-orchestrator.yaml

success "Ingress configured"

# Step 8: Test deployment
log "🧪 Step 8: Testing deployment..."

# Test internal services
for SERVICE in june-orchestrator june-stt june-tts june-idp; do
  if kubectl get service $SERVICE -n june-services >/dev/null 2>&1; then
    kubectl port-forward -n june-services svc/$SERVICE 8080:8080 &
    PF_PID=$!
    sleep 3
    
    if curl -s http://localhost:8080/healthz >/dev/null 2>&1; then
      success "$SERVICE is healthy"
    else
      warning "$SERVICE may not be ready yet"
    fi
    
    kill $PF_PID 2>/dev/null || true
  fi
done

# Final summary
success "🎉 GKE Unified deployment completed!"

log "📋 Deployment Summary:"
log "  Cluster: $CLUSTER_NAME"
log "  Harbor: $HARBOR_URL"
log "  Static IP: $STATIC_IP"
log "  Domain: $DOMAIN (configure DNS)"

log "📚 Next steps:"
log "  1. Configure DNS: $DOMAIN -> $STATIC_IP"
log "  2. Wait for SSL certificate provisioning"
log "  3. Test external access"
log "  4. Configure Harbor projects and users"
log "  5. Update CI/CD pipelines"

log "🔧 Useful commands:"
log "  kubectl get pods -n june-services"
log "  kubectl get pods -n harbor"
log "  kubectl logs -n june-services deployment/june-orchestrator"
log "  gcloud container clusters get-credentials $CLUSTER_NAME --region=$REGION"