#!/bin/bash
# June Platform - Keycloak Installation using Bitnami Helm Chart
# Simple, working Keycloak deployment

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

ROOT_DIR="$1"

if [ -z "$DOMAIN" ]; then
    if [ -z "$ROOT_DIR" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
    fi
    CONFIG_FILE="${ROOT_DIR}/config.env"
    [ ! -f "$CONFIG_FILE" ] && error "Configuration file not found: $CONFIG_FILE"
    log "Loading configuration from: $CONFIG_FILE"
    source "$CONFIG_FILE"
fi

[ -z "$DOMAIN" ] && error "DOMAIN variable is not set."

NAMESPACE="june-services"
KEYCLOAK_HOSTNAME="idp.${DOMAIN}"
DB_USERNAME="${POSTGRESQL_USERNAME:-keycloak}"
DB_PASSWORD="${POSTGRESQL_PASSWORD:-Pokemon123!}"
DB_DATABASE="${POSTGRESQL_DATABASE:-keycloak}"
ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-Pokemon123!}"

log "Installing Keycloak via Bitnami Helm chart for domain: $DOMAIN"

# Step 1: Add Bitnami repo
log "Step 1: Adding Bitnami Helm repository..."
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

success "Bitnami repo added"

# Step 2: Uninstall any existing Keycloak
log "Step 2: Removing existing Keycloak installations..."
helm uninstall keycloak -n $NAMESPACE --ignore-not-found 2>/dev/null || true
kubectl delete keycloak keycloak -n $NAMESPACE --ignore-not-found=true
kubectl delete ingress keycloak-ingress -n $NAMESPACE --ignore-not-found=true
kubectl delete deployment keycloak-operator -n $NAMESPACE --ignore-not-found=true

success "Previous installations removed"

# Step 3: Install Keycloak with Helm
log "Step 3: Installing Keycloak..."

helm upgrade --install keycloak bitnami/keycloak \
  --version 19.3.3 \
  --namespace $NAMESPACE \
  --create-namespace \
  --set auth.adminUser="$ADMIN_USER" \
  --set auth.adminPassword="$ADMIN_PASSWORD" \
  --set production=true \
  --set proxy=edge \
  --set postgresql.enabled=false \
  --set externalDatabase.host=postgresql \
  --set externalDatabase.port=5432 \
  --set externalDatabase.user="$DB_USERNAME" \
  --set externalDatabase.password="$DB_PASSWORD" \
  --set externalDatabase.database="$DB_DATABASE" \
  --set ingress.enabled=true \
  --set ingress.ingressClassName=traefik \
  --set ingress.hostname="$KEYCLOAK_HOSTNAME" \
  --set-string ingress.annotations."cert-manager\.io/cluster-issuer"=letsencrypt-prod

success "Keycloak Helm chart installed"

# Step 4: Wait for Keycloak to be ready
log "Step 4: Waiting for Keycloak to be ready..."

kubectl rollout status statefulset/keycloak -n $NAMESPACE --timeout=600s

success "Keycloak is ready"

# Step 5: Show status
log "Keycloak installation complete"
echo ""
echo "Keycloak Access Information:"
echo "  URL: https://$KEYCLOAK_HOSTNAME"
echo "  Admin Console: https://$KEYCLOAK_HOSTNAME/admin"
echo "  Admin User: $ADMIN_USER"
echo "  Admin Password: $ADMIN_PASSWORD"
echo ""
echo "Useful Commands:"
echo "  View pods:   kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=keycloak"
echo "  View logs:   kubectl logs -n $NAMESPACE -l app.kubernetes.io/name=keycloak"
echo "  View ingress: kubectl get ingress -n $NAMESPACE"
echo ""

success "Keycloak installation completed"
