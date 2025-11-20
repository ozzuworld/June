#!/bin/bash
# June Platform - Phase 9: Keycloak Operator Installation
# Deploys Keycloak using the official Keycloak Operator (quay.io images)

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
KEYCLOAK_VERSION="26.0.7"  # Use stable version
KEYCLOAK_HOSTNAME="idp.${DOMAIN}"
DB_USERNAME="${POSTGRESQL_USERNAME:-keycloak}"
DB_PASSWORD="${POSTGRESQL_PASSWORD:-Pokemon123!}"
DB_DATABASE="${POSTGRESQL_DATABASE:-keycloak}"

log "Installing Keycloak Operator for domain: $DOMAIN"

# Step 1: Install Keycloak CRDs
log "Step 1: Installing Keycloak Custom Resource Definitions..."

kubectl apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/${KEYCLOAK_VERSION}/kubernetes/keycloaks.k8s.keycloak.org-v1.yml
kubectl apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/${KEYCLOAK_VERSION}/kubernetes/keycloakrealmimports.k8s.keycloak.org-v1.yml

success "Keycloak CRDs installed"

# Step 2: Install Keycloak Operator
log "Step 2: Installing Keycloak Operator..."

# Apply operator manifests
kubectl -n $NAMESPACE apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/${KEYCLOAK_VERSION}/kubernetes/kubernetes.yml

# Patch ClusterRoleBinding for custom namespace
kubectl patch clusterrolebinding keycloak-operator-clusterrole-binding \
    --type='json' \
    -p="[{\"op\": \"replace\", \"path\": \"/subjects/0/namespace\", \"value\":\"${NAMESPACE}\"}]" \
    2>/dev/null || true

# Wait for operator to be ready
log "Waiting for Keycloak Operator to be ready..."
kubectl rollout status deployment/keycloak-operator -n $NAMESPACE --timeout=120s

success "Keycloak Operator installed"

# Step 3: Create database secret
log "Step 3: Creating database credentials secret..."

kubectl create secret generic keycloak-db-secret \
    --namespace $NAMESPACE \
    --from-literal=username=$DB_USERNAME \
    --from-literal=password=$DB_PASSWORD \
    --dry-run=client -o yaml | kubectl apply -f -

success "Database secret created"

# Step 4: Create Keycloak CR
log "Step 4: Creating Keycloak instance..."

cat <<EOF | kubectl apply -f -
apiVersion: k8s.keycloak.org/v2alpha1
kind: Keycloak
metadata:
  name: keycloak
  namespace: $NAMESPACE
spec:
  instances: 1

  # Database configuration (uses existing PostgreSQL)
  db:
    vendor: postgres
    host: postgresql
    port: 5432
    database: $DB_DATABASE
    usernameSecret:
      name: keycloak-db-secret
      key: username
    passwordSecret:
      name: keycloak-db-secret
      key: password

  # HTTP configuration (TLS termination at ingress)
  http:
    httpEnabled: true

  # Hostname configuration
  hostname:
    hostname: $KEYCLOAK_HOSTNAME
    strict: false
    strictBackchannel: false

  # Proxy configuration (behind Traefik)
  proxy:
    headers: xforwarded

  # Disable operator-managed ingress (we'll create it manually for Traefik compatibility)
  ingress:
    enabled: false

  # Features
  features:
    enabled:
      - token-exchange
      - admin-fine-grained-authz

  # Additional configuration
  additionalOptions:
    - name: health-enabled
      value: "true"
    - name: metrics-enabled
      value: "true"
    - name: log-level
      value: "INFO"

  # Resources
  resources:
    requests:
      memory: "1Gi"
      cpu: "500m"
    limits:
      memory: "2Gi"
      cpu: "1000m"
EOF

success "Keycloak CR created"

# Step 5: Wait for Keycloak service to be created
log "Step 5: Waiting for Keycloak service to be created..."
sleep 10

# Find the actual HTTP service name created by the operator (exclude discovery and operator services)
SERVICE_NAME=$(kubectl get svc -n $NAMESPACE -o name | grep keycloak | grep -v operator | grep -v discovery | head -1 | cut -d'/' -f2)

if [ -z "$SERVICE_NAME" ]; then
  warn "Keycloak HTTP service not found, checking all services..."
  kubectl get svc -n $NAMESPACE
  error "Could not find Keycloak HTTP service"
fi

log "Using service: $SERVICE_NAME"

# Step 6: Create manual ingress for Traefik compatibility
log "Step 6: Creating Traefik-compatible ingress..."

cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: keycloak-ingress
  namespace: $NAMESPACE
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.tls: "true"
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - $KEYCLOAK_HOSTNAME
      secretName: keycloak-tls
  rules:
    - host: $KEYCLOAK_HOSTNAME
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: $SERVICE_NAME
                port:
                  number: 8080
EOF

success "Keycloak ingress created"

# Step 7: Wait for Keycloak to be ready
log "Step 7: Waiting for Keycloak to be ready..."

MAX_ATTEMPTS=60
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    STATUS=$(kubectl get keycloak keycloak -n $NAMESPACE -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")

    if [ "$STATUS" = "True" ]; then
        success "Keycloak is ready!"
        break
    fi

    ATTEMPT=$((ATTEMPT + 1))
    log "Attempt $ATTEMPT/$MAX_ATTEMPTS - Keycloak status: $STATUS"
    sleep 10
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    warn "Keycloak may not be fully ready yet. Check status with:"
    echo "  kubectl get keycloak keycloak -n $NAMESPACE"
    echo "  kubectl get pods -n $NAMESPACE -l app=keycloak"
fi

# Step 8: Show status
log "Keycloak Operator installation complete"
echo ""
echo "Keycloak Access Information:"
echo "  URL: https://$KEYCLOAK_HOSTNAME"
echo "  Admin Console: https://$KEYCLOAK_HOSTNAME/admin"
echo ""
echo "Get Admin Credentials:"
echo "  Username: kubectl get secret keycloak-initial-admin -n $NAMESPACE -o jsonpath='{.data.username}' | base64 -d"
echo "  Password: kubectl get secret keycloak-initial-admin -n $NAMESPACE -o jsonpath='{.data.password}' | base64 -d"
echo ""
echo "Useful Commands:"
echo "  Check status:    kubectl get keycloak keycloak -n $NAMESPACE"
echo "  View pods:       kubectl get pods -n $NAMESPACE -l app=keycloak"
echo "  View logs:       kubectl logs -n $NAMESPACE -l app=keycloak"
echo ""

success "Keycloak Operator installation completed"
