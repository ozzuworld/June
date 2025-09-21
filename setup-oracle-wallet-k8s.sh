#!/bin/bash
# setup-oracle-wallet-k8s.sh
# FIXED: Oracle wallet setup for Kubernetes - NO HARBOR

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

# Configuration
PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
CLUSTER_NAME="${CLUSTER_NAME:-june-unified-cluster}"
REGION="${REGION:-us-central1}"

log "🔗 Setting up Oracle wallet for Kubernetes (Keycloak only - NO HARBOR)"

# Check prerequisites
if [[ ! -d "oracle-wallet" ]]; then
    error "oracle-wallet directory not found. Please run setup-oracle-wallets.sh first."
fi

# Required wallet files
REQUIRED_FILES=("cwallet.sso" "ewallet.p12" "tnsnames.ora" "sqlnet.ora")

# Verify all required files exist
for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "oracle-wallet/$file" ]]; then
        error "Required wallet file missing: oracle-wallet/$file"
    fi
done

success "All required wallet files found"

# Check if kubectl is configured
if ! kubectl cluster-info >/dev/null 2>&1; then
    log "Configuring kubectl..."
    gcloud container clusters get-credentials "$CLUSTER_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID"
fi

# Create namespace (June services only)
log "📦 Creating namespace..."
kubectl create namespace june-services --dry-run=client -o yaml | kubectl apply -f -

# Create Oracle wallet secret for Keycloak ONLY
log "🔐 Creating Oracle wallet secret for Keycloak..."
kubectl create secret generic oracle-wallet \
    --namespace=june-services \
    --from-file=cwallet.sso=oracle-wallet/cwallet.sso \
    --from-file=ewallet.p12=oracle-wallet/ewallet.p12 \
    --from-file=tnsnames.ora=oracle-wallet/tnsnames.ora \
    --from-file=sqlnet.ora=oracle-wallet/sqlnet.ora \
    --dry-run=client -o yaml | kubectl apply -f -

success "Keycloak Oracle wallet secret created"

# Create Oracle database credentials for Keycloak ONLY
log "🔑 Creating Keycloak Oracle database credentials..."
kubectl create secret generic oracle-credentials \
    --namespace=june-services \
    --from-literal=KEYCLOAK_DB_HOST="adb.us-ashburn-1.oraclecloud.com" \
    --from-literal=KEYCLOAK_DB_PORT="1522" \
    --from-literal=KEYCLOAK_DB_SERVICE="ga342747dd21cdf_keycloakdb_high.adb.oraclecloud.com" \
    --from-literal=KEYCLOAK_DB_USER="keycloak_user" \
    --from-literal=KEYCLOAK_DB_PASSWORD="KeycloakPass123!@#" \
    --from-literal=KEYCLOAK_DB_SCHEMA="keycloak_user" \
    --dry-run=client -o yaml | kubectl apply -f -

success "Keycloak Oracle credentials created"

# Create June services application secrets
log "🔑 Creating June services application secrets..."
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

success "June services secrets created"

# Verify Oracle database entries in wallet
log "🔍 Verifying Oracle database entries..."
if kubectl get secret oracle-wallet -n june-services >/dev/null 2>&1; then
    success "Oracle wallet secret exists"
    
    # Check if keycloakdb entry is in the wallet
    if kubectl get secret oracle-wallet -n june-services -o jsonpath='{.data.tnsnames\.ora}' | base64 -d | grep -q "keycloakdb_high"; then
        success "Keycloak database entry verified in wallet"
    else
        warning "Keycloak database entry not found in wallet"
    fi
else
    error "Oracle wallet secret not found"
fi

# Test Oracle wallet permissions in container
log "🧪 Testing Oracle wallet permissions in container..."
cat > /tmp/test-oracle-wallet.yaml << 'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: oracle-wallet-test
  namespace: june-services
spec:
  containers:
  - name: test
    image: oraclelinux:8-slim
    command: ['sh', '-c', 'sleep 300']
    env:
    - name: TNS_ADMIN
      value: "/opt/oracle/wallet"
    volumeMounts:
    - name: oracle-wallet
      mountPath: /opt/oracle/wallet
      readOnly: true
    resources:
      requests:
        memory: "128Mi"
        cpu: "100m"
      limits:
        memory: "256Mi"
        cpu: "200m"
  volumes:
  - name: oracle-wallet
    secret:
      secretName: oracle-wallet
      defaultMode: 0600
  restartPolicy: Never
EOF

kubectl apply -f /tmp/test-oracle-wallet.yaml

# Wait for test pod to be ready
kubectl wait --for=condition=Ready pod/oracle-wallet-test -n june-services --timeout=60s

# Test wallet files inside container
log "Testing wallet file access..."
kubectl exec oracle-wallet-test -n june-services -- sh -c '
echo "=== Oracle Wallet Test (Keycloak Only) ==="
echo "TNS_ADMIN: $TNS_ADMIN"
echo "Wallet files:"
ls -la /opt/oracle/wallet/
echo ""
echo "Testing tnsnames.ora content:"
if grep -q "keycloakdb_high" /opt/oracle/wallet/tnsnames.ora; then
    echo "✓ keycloakdb_high found"
else
    echo "✗ keycloakdb_high not found"
fi
echo ""
echo "Available database connections:"
grep -E "^[a-zA-Z].*=" /opt/oracle/wallet/tnsnames.ora | head -10
'

# Clean up test pod
kubectl delete pod oracle-wallet-test -n june-services
rm -f /tmp/test-oracle-wallet.yaml

success "Oracle wallet test completed"

# Summary and next steps
log ""
success "🎉 Oracle wallet setup completed successfully!"
log ""
log "📋 Created Kubernetes resources:"
log "  ✅ june-services/oracle-wallet secret"
log "  ✅ june-services/oracle-credentials secret"
log "  ✅ june-services/june-secrets secret"
log "  ❌ NO HARBOR resources (removed as requested)"
log ""
log "🔍 Wallet contains database connections:"
grep -E "^[a-zA-Z].*=" oracle-wallet/tnsnames.ora | sed 's/ =.*//' | while read -r db; do
    log "  ✓ $db"
done
log ""
log "🚀 Next steps:"
log "  1. Build custom Keycloak image: docker build -t keycloak-oracle June/services/june-idp/"
log "  2. Deploy Keycloak with Oracle: kubectl apply -f k8s/june-services/keycloak-oracle.yaml"
log "  3. Deploy other June services: kubectl apply -f k8s/june-services/"
log "  4. Monitor deployment: kubectl get pods -n june-services -w"
log "  5. Check Keycloak logs: kubectl logs -n june-services deployment/june-idp"
log ""
log "🔧 Useful debugging commands:"
log "  kubectl describe secret oracle-wallet -n june-services"
log "  kubectl exec -it deployment/june-idp -n june-services -- cat /opt/oracle/wallet/tnsnames.ora"
log "  kubectl logs -n june-services deployment/june-idp --previous"

success "✅ Ready for Oracle enterprise deployment (Keycloak only)!"