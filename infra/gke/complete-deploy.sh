#!/bin/bash
# step-by-step-deployment.sh - WORKING DEPLOYMENT SCRIPT (Option 2: custom VPC)

set -euo pipefail

# Colors
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

# Artifact Registry settings (keep consistent everywhere)
REPO="${REPO:-june}"
AR_HOST="${REGION}-docker.pkg.dev"
AR_IMAGE="${AR_HOST}/${PROJECT_ID}/${REPO}/june-orchestrator:latest"

log "🚀 Starting Minimal June AI Platform Deployment"
log "📋 Project: $PROJECT_ID | Region: $REGION | Cluster: $CLUSTER_NAME"

# Ensure we're in the right directory
if [[ ! -f "main.tf" ]]; then
    error "Please run this from the infra/gke directory"
fi

# Step 1: Replace the problematic main.tf
log "🔧 Step 1: Replacing Terraform configuration with working Option 2 (custom VPC)"

# Backup current file
cp main.tf "main.tf.backup.$(date +%s)"
success "Backed up current main.tf"

# Create Option-2 working configuration
cat > main.tf << 'TERRAFORM_EOF'
# Minimal working Terraform configuration (Option 2: custom VPC + subnet + secondary ranges)

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.4"
    }
  }
}

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "cluster_name" {
  description = "GKE cluster name"
  type        = string
  default     = "june-unified-cluster"
}

# Enable required APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "container.googleapis.com",
    "compute.googleapis.com",
    "sqladmin.googleapis.com",      # Cloud SQL Admin API (correct name)
    "redis.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com"
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# -----------------------------
# Network: VPC + Subnetwork with secondary ranges (for GKE)
# -----------------------------
resource "google_compute_network" "main" {
  name                    = "${var.cluster_name}-vpc"
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "main" {
  name                     = "${var.cluster_name}-${var.region}-subnet"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.main.id
  ip_cidr_range            = "10.0.0.0/16"   # primary subnet
  private_ip_google_access = true

  # Secondary ranges for GKE IP aliasing (non-overlapping + aligned)
  secondary_ip_range {
    range_name    = "${var.cluster_name}-pods"
    ip_cidr_range = "10.4.0.0/14"           # /14 => 2nd octet multiple of 4
  }

  secondary_ip_range {
    range_name    = "${var.cluster_name}-services"
    ip_cidr_range = "10.8.0.0/20"           # /20 => 3rd octet multiple of 16
  }
}


# -----------------------------
# GKE Autopilot cluster on custom VPC/Subnet
# -----------------------------
resource "google_container_cluster" "cluster" {
  name     = var.cluster_name
  location = var.region
  project  = var.project_id

  enable_autopilot = true

  network    = google_compute_network.main.id
  subnetwork = google_compute_subnetwork.main.name

  ip_allocation_policy {
    cluster_secondary_range_name  = google_compute_subnetwork.main.secondary_ip_range[0].range_name
    services_secondary_range_name = google_compute_subnetwork.main.secondary_ip_range[1].range_name
  }

  depends_on = [google_project_service.apis]
}

# -----------------------------
# Cloud SQL (public for quick start; tighten later)
# -----------------------------
resource "google_sql_database_instance" "postgres" {
  name             = "${var.cluster_name}-db"
  database_version = "POSTGRES_15"
  region           = var.region
  project          = var.project_id

  settings {
    tier = "db-f1-micro"

    ip_configuration {
      ipv4_enabled = true

      # NOTE: This is open to the world for quick tests.
      # Replace with your IP/CIDR or switch to Private IP + SQL Proxy later.
      authorized_networks {
        name  = "allow-all"
        value = "0.0.0.0/0"
      }
    }
  }

  deletion_protection = false
}

resource "google_sql_database" "june_db" {
  name     = "june_idp"
  instance = google_sql_database_instance.postgres.name
  project  = var.project_id
}

resource "random_password" "db_password" {
  length  = 16
  special = false
}

resource "google_sql_user" "june_user" {
  name     = "june_idp"
  instance = google_sql_database_instance.postgres.name
  password = random_password.db_password.result
  project  = var.project_id
}

# -----------------------------
# Memorystore for Redis on the same VPC
# -----------------------------
resource "google_redis_instance" "redis" {
  name               = "${var.cluster_name}-redis"
  tier               = "BASIC"
  memory_size_gb     = 1
  project            = var.project_id
  region             = var.region
  authorized_network = google_compute_network.main.id  # attach to custom VPC
}

# -----------------------------
# Outputs
# -----------------------------
output "cluster_name" {
  value = google_container_cluster.cluster.name
}

output "get_credentials_command" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.cluster.name} --region=${var.region} --project=${var.project_id}"
}

output "postgres_ip" {
  value = google_sql_database_instance.postgres.public_ip_address
}

output "postgres_connection" {
  value = google_sql_database_instance.postgres.connection_name
}

output "db_password" {
  value     = random_password.db_password.result
  sensitive = true
}

output "redis_host" {
  value = google_redis_instance.redis.host
}
TERRAFORM_EOF

success "Created Option-2 Terraform configuration"

# Step 2: Deploy infrastructure
log "🏗️ Step 2: Deploying infrastructure"

# Clean up old state if needed
rm -f terraform.tfstate.backup

terraform init -upgrade

# Create terraform.tfvars
cat > terraform.tfvars << EOF
project_id = "$PROJECT_ID"
region = "$REGION"
cluster_name = "$CLUSTER_NAME"
EOF

log "Running terraform plan..."
terraform plan

read -p "Continue with deployment? (y/N): " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    warning "Deployment cancelled"
    exit 0
fi

terraform apply -auto-approve

# Get outputs
POSTGRES_IP=$(terraform output -raw postgres_ip)
DB_PASSWORD=$(terraform output -raw db_password)
REDIS_HOST=$(terraform output -raw redis_host)

success "Infrastructure deployed!"
log "PostgreSQL IP: $POSTGRES_IP"
log "Redis Host: $REDIS_HOST"

# Step 3: Configure kubectl
log "🔧 Step 3: Configuring kubectl"
eval "$(terraform output -raw get_credentials_command)"

# Verify cluster access
kubectl get nodes
success "kubectl configured and cluster accessible"

# Step 4: Create Kubernetes manifests
log "📝 Step 4: Creating Kubernetes manifests"

# Go back to project root
cd ../..

# Create k8s directory structure
mkdir -p k8s/june-services

# Create basic namespace
kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f -

# Create basic deployment for orchestrator (Artifact Registry image)
cat > k8s/june-services/june-orchestrator.yaml << YAML_EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-orchestrator
  namespace: june-services
spec:
  replicas: 1
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
        image: ${AR_IMAGE}
        ports:
        - containerPort: 8080
        env:
        - name: PORT
          value: "8080"
        - name: GEMINI_API_KEY
          value: ""  # Add your key
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
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
  type: ClusterIP
---
apiVersion: v1
kind: Service
metadata:
  name: june-orchestrator-lb
  namespace: june-services
spec:
  type: ClusterIP
  selector:
    app: june-orchestrator
  ports:
  - port: 80
    targetPort: 8080
YAML_EOF

success "Created Kubernetes manifests"

# Step 5: Build and push images (Artifact Registry)
log "🐳 Step 5: Building and pushing images (Artifact Registry)"

# Enable Artifact Registry
gcloud services enable artifactregistry.googleapis.com --project="$PROJECT_ID"

# Create repo if it doesn't exist
if ! gcloud artifacts repositories describe "$REPO" --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --description="June services" \
    --project="$PROJECT_ID"
fi

# Configure Docker for AR
gcloud auth configure-docker "$AR_HOST" --quiet

# Build and push orchestrator image
if [[ -d "June/services/june-orchestrator" ]]; then
  log "Building june-orchestrator..."
  docker build -t "$AR_IMAGE" June/services/june-orchestrator/
  docker push "$AR_IMAGE"
  success "Orchestrator image pushed to Artifact Registry"
else
  error "june-orchestrator directory not found"
fi

# Step 6: Deploy services
log "🚀 Step 6: Deploying services to Kubernetes"

kubectl apply -f k8s/june-services/june-orchestrator.yaml

log "⏳ Waiting for deployment..."
kubectl wait --for=condition=available deployment/june-orchestrator -n june-services --timeout=300s

# Get LoadBalancer IP
log "Getting LoadBalancer IP..."
LB_IP=""
for i in {1..30}; do
  LB_IP=$(kubectl get service june-orchestrator-lb -n june-services -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
  if [[ -n "$LB_IP" && "$LB_IP" != "null" ]]; then
    break
  fi
  sleep 10
done

# Step 7: Test deployment
log "🧪 Step 7: Testing deployment"

if [[ -n "$LB_IP" ]]; then
  log "Testing LoadBalancer at $LB_IP..."
  sleep 30  # Wait for LB to be ready

  if curl -f "http://$LB_IP/healthz" 2>/dev/null; then
    success "Service is responding!"
    success "🎉 Basic deployment completed successfully!"
    log ""
    log "📋 Access Information:"
    log "  External IP: $LB_IP"
    log "  Health Check: http://$LB_IP/healthz"
    log "  PostgreSQL IP: $POSTGRES_IP"
    log "  Redis Host: $REDIS_HOST"
    log ""
    log "🔧 Next steps:"
    log "  1. Add your GEMINI_API_KEY to the deployment"
    log "  2. Deploy remaining services (STT, TTS, IDP)"
    log "  3. Set up proper DNS and SSL"
    log "  4. Configure service-to-service authentication"
  else
    warning "Service not responding yet, check with: kubectl logs -n june-services deployment/june-orchestrator"
  fi
else
  warning "LoadBalancer IP not ready yet, check with: kubectl get svc -n june-services"
fi

# Save deployment info
cat > deployment-status.txt << EOF
June AI Platform - Basic Deployment Status
==========================================

Deployment Time: $(date)
Project: $PROJECT_ID
Region: $REGION
Cluster: $CLUSTER_NAME

Infrastructure:
- PostgreSQL IP: $POSTGRES_IP
- Redis Host: $REDIS_HOST
- LoadBalancer IP: $LB_IP

Services Deployed:
- june-orchestrator: ✅ DEPLOYED

Next Steps:
1. Test: curl http://$LB_IP/healthz
2. Check logs: kubectl logs -n june-services deployment/june-orchestrator
3. Deploy remaining services
4. Set up external DNS

Commands:
- Connect: gcloud container clusters get-credentials $CLUSTER_NAME --region=$REGION --project=$PROJECT_ID
- Pods: kubectl get pods -n june-services
- Services: kubectl get svc -n june-services
EOF

success "Deployment information saved to deployment-status.txt"

log "🎉 Phase 1 deployment complete!"
log "Next: Deploy the remaining services one by one, then set up external access"
