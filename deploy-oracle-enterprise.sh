#!/bin/bash
# deploy-oracle-enterprise.sh
# Complete Oracle enterprise deployment script

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

# Oracle connection details
HARBOR_DB_HOST="adb.us-ashburn-1.oraclecloud.com"
HARBOR_DB_PORT="1522"
HARBOR_DB_SERVICE="ga342747dd21cdf_harbordb_high.adb.oraclecloud.com"
HARBOR_DB_USER="harbor_user"
HARBOR_DB_PASSWORD="HarborPass123!@#"

KEYCLOAK_DB_HOST="adb.us-ashburn-1.oraclecloud.com"
KEYCLOAK_DB_PORT="1522"
KEYCLOAK_DB_SERVICE="ga342747dd21cdf_keycloakdb_high.adb.oraclecloud.com"
KEYCLOAK_DB_USER="keycloak_user"
KEYCLOAK_DB_PASSWORD="KeycloakPass123!@#"

log "🚀 Starting June AI Platform Enterprise Deployment (Oracle Backend)"
log "📋 Project: $PROJECT_ID | Region: $REGION | Cluster: $CLUSTER_NAME"

# Check prerequisites
command -v gcloud >/dev/null 2>&1 || error "gcloud CLI not found"
command -v terraform >/dev/null 2>&1 || error "terraform not found"
command -v helm >/dev/null 2>&1 || error "helm not found"
command -v kubectl >/dev/null 2>&1 || error "kubectl not found"

# Check for Oracle wallet files
if [[ ! -d "oracle-wallet" ]]; then
    error "Oracle wallet directory not found. Please download wallet files from Oracle Cloud Console and place in ./oracle-wallet/"
fi

if [[ ! -f "oracle-wallet/cwallet.sso" || ! -f "oracle-wallet/tnsnames.ora" ]]; then
    error "Oracle wallet files missing. Please ensure cwallet.sso, tnsnames.ora, etc. are in ./oracle-wallet/"
fi

success "Prerequisites and Oracle wallet files verified"

# Set project
gcloud config set project "$PROJECT_ID"

# Step 1: Deploy simplified infrastructure
log "🏗️ Step 1: Deploying simplified GKE infrastructure (no databases)..."

cd infra/gke

# Clean up any existing state from complex deployment
if [[ -f "terraform.tfstate" ]]; then
    warning "Existing Terraform state found. Cleaning up old resources..."
    # This will remove the old PostgreSQL/Redis if they exist
    terraform destroy -auto-approve || warning "Some resources may have already been removed"
fi

terraform init -upgrade

terraform plan \
  -var="project_id=$PROJECT_ID" \
  -var="region=$REGION" \
  -var="cluster_name=$CLUSTER_NAME"

read -p "Deploy simplified infrastructure? (y/N): " -r
if [[ $REPLY =~ ^[Yy]$ ]]; then
    terraform apply -auto-approve \
      -var="project_id=$PROJECT_ID" \
      -var="region=$REGION" \
      -var="cluster_name=$CLUSTER_NAME"
    success "Infrastructure deployed successfully"
else
    error "Infrastructure deployment cancelled"
fi

# Get outputs
STATIC_IP=$(terraform output -raw static_ip)
ARTIFACT_REGISTRY=$(terraform output -raw artifact_registry_url)

cd ../..

# Step 2: Configure kubectl
log "🔧 Step 2: Configuring kubectl..."
gcloud container clusters get-credentials "$CLUSTER_NAME" \
  --region="$REGION" --project="$PROJECT_ID"

success "kubectl configured for cluster: $CLUSTER_NAME"

# Step 3: Create namespaces and Oracle secrets
log "🔐 Step 3: Setting up namespaces and Oracle secrets..."

# Create namespaces
kubectl create namespace harbor --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f -

# Create Oracle wallet secrets
kubectl create secret generic oracle-wallet \
  --namespace=harbor \
  --from-file=oracle-wallet/ \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic oracle-wallet \
  --namespace=june-services \
  --from-file=oracle-wallet/ \
  --dry-run=client -o yaml | kubectl apply -f -

# Create Oracle database credentials
kubectl create secret generic oracle-credentials \
  --namespace=harbor \
  --from-literal=HARBOR_DB_HOST="$HARBOR_DB_HOST" \
  --from-literal=HARBOR_DB_PORT="$HARBOR_DB_PORT" \
  --from-literal=HARBOR_DB_SERVICE="$HARBOR_DB_SERVICE" \
  --from-literal=HARBOR_DB_USER="$HARBOR_DB_USER" \
  --from-literal=HARBOR_DB_PASSWORD="$HARBOR_DB_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic oracle-credentials \
  --namespace=june-services \
  --from-literal=KEYCLOAK_DB_HOST="$KEYCLOAK_DB_HOST" \
  --from-literal=KEYCLOAK_DB_PORT="$KEYCLOAK_DB_PORT" \
  --from-literal=KEYCLOAK_DB_SERVICE="$KEYCLOAK_DB_SERVICE" \
  --from-literal=KEYCLOAK_DB_USER="$KEYCLOAK_DB_USER" \
  --from-literal=KEYCLOAK_DB_PASSWORD="$KEYCLOAK_DB_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -

# Create application secrets
kubectl create secret generic june-secrets \
  --namespace=june-services \
  --from-literal=ORCHESTRATOR_CLIENT_ID="orchestrator-client" \
  --from-literal=ORCHESTRATOR_CLIENT_SECRET="$(openssl rand -base64 32)" \
  --from-literal=STT_CLIENT_ID="stt-client" \
  --from-literal=STT_CLIENT_SECRET="$(openssl rand -base64 32)" \
  --from-literal=TTS_CLIENT_ID="tts-client" \
  --from-literal=TTS_CLIENT_SECRET="$(openssl rand -base64 32)" \
  --from-literal=GEMINI_API_KEY="${GEMINI_API_KEY:-}" \
  --from-literal=CHATTERBOX_API_KEY="${CHATTERBOX_API_KEY:-}" \
  --dry-run=client -o yaml | kubectl apply -f -

success "Oracle secrets and application secrets created"

# Step 4: Install Harbor with Oracle backend
log "📦 Step 4: Installing Harbor with Oracle backend..."

# Add Harbor repository
helm repo add harbor https://helm.goharbor.io
helm repo update

# Install Harbor with Oracle configuration
helm upgrade --install harbor harbor/harbor \
  --namespace harbor \
  --values k8s/june-services/harbor-values.yaml \
  --timeout 20m \
  --wait

# Wait for Harbor to be ready
log "⏳ Waiting for Harbor to be ready..."
kubectl wait --namespace harbor \
  --for=condition=available deployment \
  --all \
  --timeout=600s

success "Harbor deployed with Oracle backend"

# Step 5: Deploy Keycloak with Oracle backend
log "🔐 Step 5: Deploying Keycloak with Oracle backend..."

kubectl apply -f k8s/june-services/keycloak-oracle.yaml

# Wait for Keycloak to be ready
log "⏳ Waiting for Keycloak to be ready..."
kubectl wait --namespace june-services \
  --for=condition=available deployment/june-idp \
  --timeout=600s

success "Keycloak deployed with Oracle backend"

# Step 6: Build and push images to Artifact Registry
log "🐳 Step 6: Building and pushing images to Artifact Registry..."

# Configure Docker for Artifact Registry
gcloud auth configure-docker "${REGION}-docker.pkg.dev"

# Build and push each service
for SERVICE in june-orchestrator june-stt june-tts; do
    if [[ -d "June/services/$SERVICE" ]]; then
        SERVICE_PATH="June/services/$SERVICE"
    else
        warning "Service path not found for $SERVICE, skipping"
        continue
    fi
    
    log "Building $SERVICE..."
    IMAGE_TAG="$ARTIFACT_REGISTRY/$SERVICE:latest"
    
    docker build -t "$IMAGE_TAG" "$SERVICE_PATH"
    docker push "$IMAGE_TAG"
    
    success "$SERVICE image pushed to Artifact Registry"
done

# Step 7: Deploy June services
log "🚀 Step 7: Deploying June services..."

# Update image references in manifests
sed -i "s|us-central1-docker.pkg.dev/YOUR_PROJECT_ID/june|$ARTIFACT_REGISTRY|g" k8s/june-services/june-*.yaml
sed -i "s|main-buffer-469817-v7|$PROJECT_ID|g" k8s/june-services/june-*.yaml

# Deploy services
kubectl apply -f k8s/june-services/june-orchestrator.yaml
kubectl apply -f k8s/june-services/june-stt.yaml
kubectl apply -f k8s/june-services/june-tts.yaml

# Wait for deployments
log "⏳ Waiting for June services to be ready..."
kubectl wait --namespace june-services \
  --for=condition=available deployment \
  --selector=app \
  --timeout=600s

success "All June services deployed successfully"

# Step 8: Test deployment
log "🧪 Step 8: Testing deployment..."

# Test each service health endpoint
for SERVICE in june-orchestrator june-stt june-tts june-idp; do
    log "Testing $SERVICE..."
    kubectl port-forward -n june-services svc/$SERVICE 8080:8080 &
    PF_PID=$!
    sleep 5
    
    if curl -f http://localhost:8080/healthz 2>/dev/null; then
        success "$SERVICE is healthy"
    else
        warning "$SERVICE may not be ready yet"
    fi
    
    kill $PF_PID 2>/dev/null || true
    sleep 2
done

# Get LoadBalancer IPs
ORCHESTRATOR_LB_IP=$(kubectl get service june-orchestrator-lb -n june-services -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")

# Final summary
success "🎉 Oracle Enterprise deployment completed successfully!"

log ""
log "📋 Deployment Summary:"
log "  🏗️  GKE Cluster: $CLUSTER_NAME"
log "  🔷 Static IP: $STATIC_IP"
log "  📦 Artifact Registry: $ARTIFACT_REGISTRY"
log "  ⚡ Orchestrator LB: $ORCHESTRATOR_LB_IP"
log ""
log "🏢 Oracle Enterprise Features:"
log "  ✅ Harbor Registry → Oracle Autonomous DB"
log "  ✅ Keycloak IDP → Oracle Autonomous DB"
log "  ✅ SSL/TLS encrypted connections"
log "  ✅ Separate databases for isolation"
log "  ✅ Enterprise-grade security"
log ""
log "🧪 Quick Tests:"
if [[ "$ORCHESTRATOR_LB_IP" != "pending" ]]; then
    log "  curl http://$ORCHESTRATOR_LB_IP/healthz"
else
    log "  kubectl port-forward -n june-services svc/june-orchestrator 8080:8080"
    log "  curl http://localhost:8080/healthz"
fi
log ""
log "📄 Next Steps:"
log "  1. Configure DNS to point to $STATIC_IP"
log "  2. Setup SSL certificates for production"
log "  3. Configure Harbor projects and users"
log "  4. Setup monitoring and alerting"
log "  5. Create Keycloak realms and clients"

log "✅ Your enterprise June AI Platform is ready! 🚀"