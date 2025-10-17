#!/bin/bash
# OpenCTI Installation Script for June Platform
# Deploys OpenCTI Cyber Threat Intelligence Platform

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️${NC} $1"; }
error() { echo -e "${RED}❌${NC} $1"; exit 1; }

echo "==========================================="
echo "OpenCTI Installation for June Platform"
echo "==========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    error "Please run as root (sudo ./install-opencti.sh)"
fi

# Configuration
NAMESPACE="opencti"
RELEASE_NAME="opencti"
DOMAIN="${DOMAIN:-ozzu.world}"
CTI_DOMAIN="cti.${DOMAIN}"

log "Configuration:"
echo "  Namespace: $NAMESPACE"
echo "  Release: $RELEASE_NAME"
echo "  Domain: $CTI_DOMAIN"
echo ""

# Verify prerequisites
log "Checking prerequisites..."

if ! command -v kubectl &> /dev/null; then
    error "kubectl not found. Please install kubectl first."
fi

if ! command -v helm &> /dev/null; then
    error "helm not found. Please install helm first."
fi

if ! kubectl cluster-info &> /dev/null; then
    error "Cannot connect to Kubernetes cluster"
fi

success "Prerequisites check passed"

# Add Helm repository
log "Adding OpenCTI Helm repository..."
helm repo add opencti https://devops-ia.github.io/helm-opencti > /dev/null 2>&1 || true
helm repo update > /dev/null 2>&1
success "Helm repository added"

# Create namespace
log "Creating namespace..."
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
success "Namespace created: $NAMESPACE"

# Generate secure tokens
log "Generating secure tokens..."
ADMIN_TOKEN=$(uuidgen 2>/dev/null || python3 -c "import uuid; print(str(uuid.uuid4()))")
ADMIN_PASSWORD="OpenCTI$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-12)"
RABBITMQ_PASSWORD="RabbitMQ$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-12)"
MINIO_PASSWORD="MinIO$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-12)"
HEALTH_ACCESS_KEY="Health$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-12)"

success "Secure tokens generated"

# Create Kubernetes secret for sensitive data
log "Creating Kubernetes secrets..."
kubectl create secret generic opencti-secrets \
    --from-literal=admin-token="$ADMIN_TOKEN" \
    --from-literal=admin-password="$ADMIN_PASSWORD" \
    --from-literal=rabbitmq-password="$RABBITMQ_PASSWORD" \
    --from-literal=minio-password="$MINIO_PASSWORD" \
    --from-literal=health-access-key="$HEALTH_ACCESS_KEY" \
    --namespace=$NAMESPACE \
    --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1

success "Kubernetes secrets created"

# Check if values file exists
VALUES_FILE="opencti-values.yaml"
if [ ! -f "$VALUES_FILE" ]; then
    error "Values file not found: $VALUES_FILE. Please create it first."
fi

# Update values file with generated secrets (in-place)
log "Updating values file with secrets..."
cp "$VALUES_FILE" "${VALUES_FILE}.backup"

# Create a temporary values file with secrets
cat > opencti-secrets-override.yaml << EOF
# Auto-generated secrets override
env:
  APP__ADMIN__TOKEN: "$ADMIN_TOKEN"
  APP__ADMIN__PASSWORD: "$ADMIN_PASSWORD"
  APP__HEALTH_ACCESS_KEY: "$HEALTH_ACCESS_KEY"
  RABBITMQ__PASSWORD: "$RABBITMQ_PASSWORD"

ingress:
  hosts:
    - host: $CTI_DOMAIN
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: ${DOMAIN//\./-}-wildcard-tls
      hosts:
        - $CTI_DOMAIN

minio:
  auth:
    rootPassword: "$MINIO_PASSWORD"

rabbitmq:
  auth:
    password: "$RABBITMQ_PASSWORD"
    erlangCookie: "$(openssl rand -base64 32 | tr -d '/+=')"

worker:
  env:
    OPENCTI_TOKEN: "$ADMIN_TOKEN"
EOF

success "Secrets configuration prepared"

# Set vm.max_map_count for ElasticSearch (required)
log "Configuring system for ElasticSearch..."
if sysctl vm.max_map_count | grep -q "262144"; then
    log "vm.max_map_count already set correctly"
else
    sysctl -w vm.max_map_count=262144
    echo "vm.max_map_count=262144" >> /etc/sysctl.conf
    success "vm.max_map_count configured"
fi

# Install/Upgrade OpenCTI
log "Installing OpenCTI..."
log "This may take 10-15 minutes as it downloads and starts all components..."

helm upgrade --install $RELEASE_NAME opencti/opencti \
    --namespace=$NAMESPACE \
    --values=$VALUES_FILE \
    --values=opencti-secrets-override.yaml \
    --timeout=20m \
    --wait \
    --debug 2>&1 | tee opencti-install.log

if [ $? -eq 0 ]; then
    success "OpenCTI deployed successfully"
else
    error "OpenCTI deployment failed. Check opencti-install.log for details"
fi

# Wait for pods to be ready
log "Waiting for OpenCTI pods to be ready..."
kubectl wait --for=condition=Ready pods \
    --selector=app.kubernetes.io/name=opencti \
    --namespace=$NAMESPACE \
    --timeout=600s || warn "Some pods may still be starting"

# Check pod status
log "OpenCTI pod status:"
kubectl get pods -n $NAMESPACE

# Save credentials
CREDS_FILE="opencti-credentials.txt"
cat > $CREDS_FILE << EOF
=====================================
OpenCTI Installation Credentials
=====================================

Access URL: https://$CTI_DOMAIN
Admin Email: admin@${DOMAIN}
Admin Password: $ADMIN_PASSWORD
Admin Token (API): $ADMIN_TOKEN

Health Access Key: $HEALTH_ACCESS_KEY

Component Passwords:
- RabbitMQ: $RABBITMQ_PASSWORD
- MinIO: $MINIO_PASSWORD

Namespace: $NAMESPACE
Release Name: $RELEASE_NAME

Generated: $(date)
=====================================

IMPORTANT: Store these credentials securely and delete this file!

Commands:
- View pods: kubectl get pods -n $NAMESPACE
- View logs: kubectl logs -l app.kubernetes.io/name=opencti -n $NAMESPACE
- Access service: kubectl port-forward -n $NAMESPACE svc/opencti 8080:8080
- Check ingress: kubectl get ingress -n $NAMESPACE
=====================================
EOF

chmod 600 $CREDS_FILE
success "Credentials saved to: $CREDS_FILE"

# Check ingress
log "Checking ingress configuration..."
kubectl get ingress -n $NAMESPACE

# Final summary
echo ""
echo "==========================================="
success "OpenCTI Installation Complete!"
echo "==========================================="
echo ""
echo "📋 Access Information:"
echo "  URL: https://$CTI_DOMAIN"
echo "  Email: admin@${DOMAIN}"
echo "  Password: (saved in $CREDS_FILE)"
echo ""
echo "🔒 IMPORTANT: Delete the credentials file after saving:"
echo "  rm $CREDS_FILE"
echo ""
echo "📊 Status Commands:"
echo "  kubectl get pods -n $NAMESPACE"
echo "  kubectl get svc -n $NAMESPACE"
echo "  kubectl get ingress -n $NAMESPACE"
echo "  kubectl logs -l app.kubernetes.io/name=opencti -n $NAMESPACE"
echo ""
echo "🔧 Troubleshooting:"
echo "  kubectl describe pods -n $NAMESPACE"
echo "  kubectl logs -l app.kubernetes.io/name=opencti -n $NAMESPACE --previous"
echo "  helm status $RELEASE_NAME -n $NAMESPACE"
echo ""
echo "📝 DNS Configuration Required:"
echo "  Add DNS record: $CTI_DOMAIN A <your-external-ip>"
echo ""
echo "🔌 Optional: Install Connectors"
echo "  Edit opencti-values.yaml to enable connectors for:"
echo "  - MISP, CVE, AlienVault OTX, MITRE ATT&CK, etc."
echo ""
echo "==========================================="

# Cleanup temporary files
rm -f opencti-secrets-override.yaml
log "Cleaned up temporary files"

success "Installation completed successfully!"