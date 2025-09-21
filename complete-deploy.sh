#!/bin/bash
# manual-deploy-from-gke.sh - Deploy from infra/gke directory

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
DOMAIN="${DOMAIN:-allsafe.world}"
API_DOMAIN="api.${DOMAIN}"
HARBOR_DOMAIN="harbor.${DOMAIN}"
AUTH_DOMAIN="auth.${DOMAIN}"

# Required secrets - prompt user if not set
if [[ -z "${ORCHESTRATOR_CLIENT_SECRET:-}" ]]; then
    ORCHESTRATOR_CLIENT_SECRET=$(openssl rand -base64 32)
    warning "Generated ORCHESTRATOR_CLIENT_SECRET: $ORCHESTRATOR_CLIENT_SECRET"
fi

if [[ -z "${STT_CLIENT_SECRET:-}" ]]; then
    STT_CLIENT_SECRET=$(openssl rand -base64 32)
    warning "Generated STT_CLIENT_SECRET: $STT_CLIENT_SECRET"
fi

if [[ -z "${TTS_CLIENT_SECRET:-}" ]]; then
    TTS_CLIENT_SECRET=$(openssl rand -base64 32)
    warning "Generated TTS_CLIENT_SECRET: $TTS_CLIENT_SECRET"
fi

if [[ -z "${KC_DB_PASSWORD:-}" ]]; then
    KC_DB_PASSWORD=$(openssl rand -base64 32)
    warning "Generated KC_DB_PASSWORD: $KC_DB_PASSWORD"
fi

GEMINI_API_KEY="${GEMINI_API_KEY:-}"
CHATTERBOX_API_KEY="${CHATTERBOX_API_KEY:-}"

log "🚀 Starting June AI Platform Deployment from infra/gke"
log "📋 Configuration:"
log "   Project: $PROJECT_ID"
log "   Region: $REGION"
log "   Domain: $DOMAIN"
log "   Current directory: $(pwd)"

# Verify prerequisites
command -v gcloud >/dev/null 2>&1 || error "gcloud CLI not found"
command -v terraform >/dev/null 2>&1 || error "terraform not found"
command -v helm >/dev/null 2>&1 || error "helm not found"
command -v kubectl >/dev/null 2>&1 || error "kubectl not found"

# Set project
gcloud config set project "$PROJECT_ID"

# Step 1: Deploy Infrastructure (we're already in infra/gke)
log "🏗️ Step 1: Deploying GKE Autopilot infrastructure..."

if [[ ! -f "main.tf" ]]; then
    error "main.tf not found. Please run this script from the infra/gke directory or project root."
fi

terraform init -upgrade

# Create terraform.tfvars
cat > terraform.tfvars << EOF
project_id = "$PROJECT_ID"
region = "$REGION"
cluster_name = "$CLUSTER_NAME"
harbor_domain = "$HARBOR_DOMAIN"
EOF

log "Running Terraform plan..."
terraform plan

read -p "Continue with Terraform apply? (y/N): " -r
if [[ $REPLY =~ ^[Yy]$ ]]; then
    terraform apply -auto-approve
    success "Infrastructure deployed successfully"
else
    error "Deployment cancelled by user"
fi

# Get infrastructure outputs
POSTGRES_IP=$(terraform output -raw postgres_connection_name | cut -d: -f1)
REDIS_HOST=$(terraform output -raw redis_host)
HARBOR_BUCKET=$(terraform output -raw harbor_registry_bucket)

log "Infrastructure outputs:"
log "  PostgreSQL IP: $POSTGRES_IP"
log "  Redis Host: $REDIS_HOST"
log "  Harbor Bucket: $HARBOR_BUCKET"

# Step 2: Configure kubectl
log "🔧 Step 2: Configuring kubectl..."
gcloud container clusters get-credentials "$CLUSTER_NAME" \
  --region="$REGION" --project="$PROJECT_ID"

success "kubectl configured"

# Step 3: Install Harbor
log "📦 Step 3: Installing Harbor registry..."

helm repo add harbor https://helm.goharbor.io
helm repo update

# Create harbor namespace
kubectl create namespace harbor --dry-run=client -o yaml | kubectl apply -f -

# Get database password from terraform output
HARBOR_DB_PASSWORD=$(terraform output -raw harbor_db_password)

# Create Harbor values
cat > /tmp/harbor-values.yaml << EOF
expose:
  type: loadBalancer
  loadBalancer:
    IP: ""
  tls:
    enabled: false  # We'll handle SSL via ingress
    
externalURL: https://$HARBOR_DOMAIN

harborAdminPassword: "Harbor12345"

database:
  type: external
  external:
    host: "$POSTGRES_IP"
    port: "5432"
    username: "harbor"
    password: "$HARBOR_DB_PASSWORD"
    coreDatabase: "harbor"
    sslmode: "require"
    
redis:
  type: external
  external:
    addr: "$REDIS_HOST:6379"

registry:
  storage:
    gcs:
      bucket: "$HARBOR_BUCKET"
      
# Autopilot resource requirements
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
      cpu: 50m
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
        cpu: 50m
      limits:
        memory: 256Mi
        cpu: 200m

serviceAccount:
  create: false
  name: "harbor"
EOF

# Install Harbor
log "Installing Harbor (this may take 10-15 minutes)..."
helm upgrade --install harbor harbor/harbor \
  --namespace harbor \
  --values /tmp/harbor-values.yaml \
  --timeout 20m \
  --wait

# Get Harbor LoadBalancer IP
log "⏳ Waiting for Harbor LoadBalancer IP..."
HARBOR_IP=""
for i in {1..30}; do
  HARBOR_IP=$(kubectl get service harbor -n harbor -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
  if [[ -n "$HARBOR_IP" && "$HARBOR_IP" != "null" ]]; then
    break
  fi
  sleep 10
  echo "Waiting for LoadBalancer IP... ($i/30)"
done

if [[ -z "$HARBOR_IP" ]]; then
    error "Harbor LoadBalancer IP not available after 5 minutes"
fi

success "Harbor installed at IP: $HARBOR_IP"
rm -f /tmp/harbor-values.yaml

# Step 4: Create application secrets
log "🔐 Step 4: Creating application secrets..."

kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic june-secrets \
  --namespace=june-services \
  --from-literal=ORCHESTRATOR_CLIENT_ID="orchestrator-client" \
  --from-literal=ORCHESTRATOR_CLIENT_SECRET="$ORCHESTRATOR_CLIENT_SECRET" \
  --from-literal=STT_CLIENT_ID="stt-client" \
  --from-literal=STT_CLIENT_SECRET="$STT_CLIENT_SECRET" \
  --from-literal=TTS_CLIENT_ID="tts-client" \
  --from-literal=TTS_CLIENT_SECRET="$TTS_CLIENT_SECRET" \
  --from-literal=GEMINI_API_KEY="$GEMINI_API_KEY" \
  --from-literal=CHATTERBOX_API_KEY="$CHATTERBOX_API_KEY" \
  --from-literal=KC_DB_PASSWORD="$KC_DB_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -

success "Application secrets created"

# Step 5: Build and push images (need to go to project root)
log "🐳 Step 5: Building and pushing images to Harbor..."

# Go back to project root
cd ../..

# Setup Docker for Harbor
HARBOR_URL="$HARBOR_IP"
docker login $HARBOR_URL -u admin -p Harbor12345

# Create Harbor project
curl -k -X POST "http://$HARBOR_URL/api/v2.0/projects" \
  -H "Content-Type: application/json" \
  -u "admin:Harbor12345" \
  -d '{"project_name":"june","public":true}' || true

# Build and push each service
for SERVICE in june-orchestrator june-stt june-tts june-idp; do
  if [[ -d "June/services/$SERVICE" ]]; then
    SERVICE_PATH="June/services/$SERVICE"
  elif [[ -d "services/$SERVICE" ]]; then
    SERVICE_PATH="services/$SERVICE"
  else
    warning "Service path not found for $SERVICE, skipping"
    continue
  fi
  
  if [[ ! -f "$SERVICE_PATH/Dockerfile" ]]; then
    warning "Dockerfile not found for $SERVICE at $SERVICE_PATH, skipping"
    continue
  fi
  
  log "Building $SERVICE from $SERVICE_PATH..."
  IMAGE_TAG="$HARBOR_URL/june/$SERVICE:latest"
  COMMIT_SHA_TAG="$HARBOR_URL/june/$SERVICE:$(git rev-parse --short HEAD 2>/dev/null || echo 'manual')"
  
  docker build -t "$IMAGE_TAG" -t "$COMMIT_SHA_TAG" "$SERVICE_PATH"
  docker push "$IMAGE_TAG"
  docker push "$COMMIT_SHA_TAG"
  
  success "$SERVICE pushed to Harbor"
done

# Step 6: Deploy June services
log "🚀 Step 6: Deploying June services..."

# Check if k8s manifests exist
if [[ ! -d "k8s/june-services" ]]; then
    warning "k8s/june-services directory not found, creating manifests..."
    mkdir -p k8s/june-services
    
    # Create a basic manifest file
    cat > k8s/june-services/june-services.yaml << 'MANIFEST_EOF'
# Basic June services manifest - you'll need to customize this
apiVersion: v1
kind: Namespace
metadata:
  name: june-services
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-orchestrator
  namespace: june-services
spec:
  replicas: 2
  selector:
    matchLabels:
      app: june-orchestrator
  template:
    metadata:
      labels:
        app: june-orchestrator
    spec:
      containers:
      - name: june-orchestrator
        image: HARBOR_URL/june/june-orchestrator:latest
        ports:
        - containerPort: 8080
        env:
        - name: PORT
          value: "8080"
        resources:
          requests:
            memory: 256Mi
            cpu: 100m
          limits:
            memory: 512Mi
            cpu: 500m
---
apiVersion: v1
kind: Service
metadata:
  name: june-orchestrator
  namespace: june-services
spec:
  selector:
    app: june-orchestrator
  ports:
  - port: 8080
    targetPort: 8080
MANIFEST_EOF
fi

# Update manifests with Harbor URL and database info
find k8s/june-services -name "*.yaml" -exec sed -i.bak "s|harbor\.yourdomain\.com|$HARBOR_URL|g" {} \;
find k8s/june-services -name "*.yaml" -exec sed -i.bak "s|HARBOR_URL|$HARBOR_URL|g" {} \;
find k8s/june-services -name "*.yaml" -exec sed -i.bak "s|api\.yourdomain\.com|$API_DOMAIN|g" {} \;
find k8s/june-services -name "*.yaml" -exec sed -i.bak "s|POSTGRES_HOST|$POSTGRES_IP|g" {} \;

# Apply service accounts first
kubectl apply -f - << 'EOF'
apiVersion: v1
kind: ServiceAccount
metadata:
  name: june-orchestrator
  namespace: june-services
---
apiVersion: v1
kind: ServiceAccount  
metadata:
  name: june-stt
  namespace: june-services
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: june-tts
  namespace: june-services
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: june-idp
  namespace: june-services
EOF

# Deploy services
kubectl apply -f k8s/june-services/

log "⏳ Waiting for deployments to be ready..."
kubectl wait --namespace june-services \
  --for=condition=available deployment \
  --all --timeout=600s || warning "Some deployments may still be starting"

success "Services deployed!"

# Step 7: Setup external access
log "🌐 Step 7: Setting up external access..."

# Create global static IP
gcloud compute addresses create june-api-ip --global --project="$PROJECT_ID" || true
API_STATIC_IP=$(gcloud compute addresses describe june-api-ip --global --format="value(address)")

log "Static IP: $API_STATIC_IP"

success "🎉 Deployment completed!"

log ""
log "📋 Deployment Summary:"
log "  🏗️  GKE Cluster: $CLUSTER_NAME"
log "  📦 Harbor Registry: http://$HARBOR_IP (admin/Harbor12345)"  
log "  🌐 API Static IP: $API_STATIC_IP"
log "  🔐 Auth Domain: $AUTH_DOMAIN"
log "  📡 API Domain: $API_DOMAIN"
log ""
log "🔧 IMPORTANT - Configure Cloudflare DNS:"
log "  1. Add A record: api.$DOMAIN → $API_STATIC_IP (Proxied)"
log "  2. Add A record: auth.$DOMAIN → $API_STATIC_IP (Proxied)"  
log "  3. Add A record: harbor.$DOMAIN → $HARBOR_IP (DNS Only)"
log ""
log "🔑 Generated Secrets (save these!):"
log "  ORCHESTRATOR_CLIENT_SECRET: $ORCHESTRATOR_CLIENT_SECRET"
log "  STT_CLIENT_SECRET: $STT_CLIENT_SECRET"
log "  TTS_CLIENT_SECRET: $TTS_CLIENT_SECRET"
log "  KC_DB_PASSWORD: $KC_DB_PASSWORD"
log ""
log "📄 Next steps:"
log "  1. Configure DNS records in Cloudflare"
log "  2. Wait for SSL certificate provisioning"
log "  3. Test: kubectl get pods -n june-services"

# Save important info to file
cat > ../../deployment-info.txt << EOF
June AI Platform Deployment Information
=====================================

Cluster: $CLUSTER_NAME
Project: $PROJECT_ID
Region: $REGION

Static IPs:
- API: $API_STATIC_IP
- Harbor: $HARBOR_IP

Domains:
- API: $API_DOMAIN
- Auth: $AUTH_DOMAIN  
- Harbor: $HARBOR_DOMAIN

Generated Secrets:
- ORCHESTRATOR_CLIENT_SECRET: $ORCHESTRATOR_CLIENT_SECRET
- STT_CLIENT_SECRET: $STT_CLIENT_SECRET
- TTS_CLIENT_SECRET: $TTS_CLIENT_