#!/bin/bash
# deploy-idp-step-by-step.sh - Add Keycloak IDP with Oracle database

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
error() { echo -e "${RED}❌ $1${NC}"; }

log "🔐 Step-by-Step IDP (Keycloak + Oracle) Deployment"
log "Current core services are running, now adding authentication layer"

# Verify core services are running
log "Step 0: Verifying core services are running"
if ! kubectl get pods -n june-services | grep -q "Running"; then
    error "Core services not running. Run the immediate fix script first."
fi
success "Core services verified - proceeding with IDP"

# Step 1: Create Oracle wallet secret (FIXED)
log "Step 1: Creating Oracle wallet secret with proper file handling"

# Check if wallet files exist
WALLET_DIR="k8s/june-services/keycloakdb_wallet"
if [[ ! -d "$WALLET_DIR" ]]; then
    error "Wallet directory not found: $WALLET_DIR"
    log "Please ensure wallet files are in: $WALLET_DIR/"
    exit 1
fi

# Verify required wallet files exist
REQUIRED_FILES=("cwallet.sso" "ewallet.p12" "tnsnames.ora" "sqlnet.ora")
for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$WALLET_DIR/$file" ]]; then
        error "Missing wallet file: $WALLET_DIR/$file"
        exit 1
    fi
done
success "All wallet files found"

# Delete existing wallet secret if exists
kubectl delete secret oracle-wallet -n june-services --ignore-not-found=true

# Create wallet secret from files (not base64 encoded strings)
kubectl create secret generic oracle-wallet -n june-services \
    --from-file=cwallet.sso="$WALLET_DIR/cwallet.sso" \
    --from-file=ewallet.p12="$WALLET_DIR/ewallet.p12" \
    --from-file=tnsnames.ora="$WALLET_DIR/tnsnames.ora" \
    --from-file=sqlnet.ora="$WALLET_DIR/sqlnet.ora"

success "Oracle wallet secret created"

# Step 2: Create Oracle credentials secret
log "Step 2: Creating Oracle database credentials"

kubectl delete secret oracle-credentials -n june-services --ignore-not-found=true

kubectl create secret generic oracle-credentials -n june-services \
    --from-literal=DB_HOST="adb.us-ashburn-1.oraclecloud.com" \
    --from-literal=DB_PORT="1522" \
    --from-literal=DB_SERVICE="ga342747dd21cdf_keycloakdb_high.adb.oraclecloud.com" \
    --from-literal=DB_USER="keycloak_user" \
    --from-literal=DB_PASSWORD="KeycloakPass123!@#"

success "Oracle credentials secret created"

# Step 3: Create Keycloak admin credentials
log "Step 3: Creating Keycloak admin credentials"

kubectl delete secret keycloak-admin -n june-services --ignore-not-found=true

kubectl create secret generic keycloak-admin -n june-services \
    --from-literal=KEYCLOAK_ADMIN="admin" \
    --from-literal=KEYCLOAK_ADMIN_PASSWORD="admin123456"

success "Keycloak admin credentials created"

# Step 4: Create Keycloak deployment with FIXED configuration
log "Step 4: Creating Keycloak deployment with fixed Oracle configuration"

cat > k8s/june-services/keycloak-oracle-fixed.yaml << 'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: keycloak-config
  namespace: june-services
data:
  # FIXED: Simplified Oracle configuration
  KC_DB: "oracle"
  KC_DB_URL: "jdbc:oracle:thin:@keycloakdb_high?TNS_ADMIN=/opt/oracle/wallet"
  KC_DB_USERNAME: "keycloak_user"
  KC_HOSTNAME_STRICT: "false"
  KC_HTTP_ENABLED: "true"
  KC_HEALTH_ENABLED: "true"
  KC_METRICS_ENABLED: "true"
  KC_TRANSACTION_XA_ENABLED: "false"
  KC_CACHE: "local"
  KC_LOG_LEVEL: "INFO"
  KC_PROXY: "edge"
  # Oracle environment
  TNS_ADMIN: "/opt/oracle/wallet"
  ORACLE_HOME: "/opt/oracle"
  # FIXED: Disable clustering completely
  JAVA_OPTS_APPEND: "-XX:MaxRAMPercentage=70.0 -XX:+UseContainerSupport -Dkeycloak.connectionsInfinispan.default.clustered=false -Djgroups.tcp.address=127.0.0.1"

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-idp
  namespace: june-services
  labels:
    app: june-idp
spec:
  # FIXED: Single replica only
  replicas: 1
  selector:
    matchLabels:
      app: june-idp
  template:
    metadata:
      labels:
        app: june-idp
    spec:
      securityContext:
        runAsNonRoot: false
        fsGroup: 1000
      
      initContainers:
      # FIXED: Better wallet setup
      - name: setup-wallet
        image: oraclelinux:8-slim
        command: ['sh', '-c']
        args:
          - |
            echo "=== Oracle Wallet Setup ==="
            echo "Setting up file permissions..."
            chmod 644 /opt/oracle/wallet/*
            echo "Wallet files:"
            ls -la /opt/oracle/wallet/
            echo ""
            echo "Checking tnsnames.ora content:"
            echo "Looking for keycloakdb_high entry..."
            grep -A 3 "keycloakdb_high" /opt/oracle/wallet/tnsnames.ora || echo "ERROR: keycloakdb_high not found!"
            echo ""
            echo "Checking sqlnet.ora:"
            cat /opt/oracle/wallet/sqlnet.ora
            echo ""
            echo "Wallet setup complete!"
        volumeMounts:
        - name: oracle-wallet
          mountPath: /opt/oracle/wallet
        resources:
          requests:
            memory: "64Mi"
            cpu: "50m"
          limits:
            memory: "128Mi"
            cpu: "100m"
      
      # Test Oracle connectivity
      - name: test-oracle
        image: busybox:1.35
        command: ['sh', '-c']
        args:
          - |
            echo "=== Testing Oracle Connectivity ==="
            echo "Testing TCP connection to Oracle..."
            timeout 10 nc -zv adb.us-ashburn-1.oraclecloud.com 1522 && echo "✅ Oracle port 1522 reachable" || echo "❌ Cannot reach Oracle port 1522"
            echo "Oracle connectivity test complete"
        resources:
          requests:
            memory: "32Mi"
            cpu: "25m"
          limits:
            memory: "64Mi"
            cpu: "50m"
      
      containers:
      - name: keycloak
        image: quay.io/keycloak/keycloak:23.0.0
        args:
          - "start"
          - "--db=oracle"
          - "--http-enabled=true"
          - "--hostname-strict=false"
          - "--proxy=edge"
          - "--transaction-xa-enabled=false"
          - "--cache=local"
          - "--health-enabled=true"
          - "--metrics-enabled=true"
          - "--log-level=INFO"
        
        ports:
        - name: http
          containerPort: 8080
        
        # Environment from ConfigMap
        envFrom:
        - configMapRef:
            name: keycloak-config
        
        # Environment from Secrets
        env:
        - name: KC_DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: oracle-credentials
              key: DB_PASSWORD
        - name: KEYCLOAK_ADMIN
          valueFrom:
            secretKeyRef:
              name: keycloak-admin
              key: KEYCLOAK_ADMIN
        - name: KEYCLOAK_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: keycloak-admin
              key: KEYCLOAK_ADMIN_PASSWORD
        
        # Mount Oracle wallet
        volumeMounts:
        - name: oracle-wallet
          mountPath: /opt/oracle/wallet
          readOnly: true
        
        # FIXED: Minimal resources like other services
        resources:
          requests:
            memory: "512Mi"
            cpu: "200m"
          limits:
            memory: "1Gi"
            cpu: "400m"
        
        # FIXED: Longer timeouts for Oracle connection
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 180
          periodSeconds: 30
          timeoutSeconds: 10
          failureThreshold: 5
        
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 120
          periodSeconds: 15
          timeoutSeconds: 10
          failureThreshold: 10
        
        # Extended startup probe for Oracle
        startupProbe:
          httpGet:
            path: /health/started
            port: 8080
          initialDelaySeconds: 60
          periodSeconds: 20
          timeoutSeconds: 10
          failureThreshold: 60  # Up to 20 minutes
      
      volumes:
      - name: oracle-wallet
        secret:
          secretName: oracle-wallet
          defaultMode: 0644

---
apiVersion: v1
kind: Service
metadata:
  name: june-idp
  namespace: june-services
  labels:
    app: june-idp
spec:
  type: ClusterIP
  ports:
  - name: http
    port: 8080
    targetPort: 8080
  selector:
    app: june-idp

---
# Temporary LoadBalancer for testing
apiVersion: v1
kind: Service
metadata:
  name: june-idp-lb
  namespace: june-services
  labels:
    app: june-idp
spec:
  type: LoadBalancer
  ports:
  - name: http
    port: 80
    targetPort: 8080
  selector:
    app: june-idp
EOF

success "Keycloak deployment manifest created"

# Step 5: Apply the configuration
log "Step 5: Applying Keycloak configuration"

kubectl apply -f k8s/june-services/keycloak-oracle-fixed.yaml

success "Keycloak deployment applied"

# Step 6: Monitor deployment
log "Step 6: Monitoring Keycloak deployment (this may take several minutes)"

echo ""
log "📊 Watching pods start up..."
kubectl get pods -n june-services -w --timeout=30s || true

echo ""
log "🔍 Checking deployment status..."
kubectl get deployment june-idp -n june-services

echo ""
log "📋 Recent events:"
kubectl get events -n june-services --sort-by='.lastTimestamp' --field-selector reason!=Scheduled | tail -10

echo ""
success "✅ IDP deployment initiated!"
echo ""
echo "🚀 Next steps:"
echo "  1. Monitor startup: kubectl logs -f deployment/june-idp -n june-services"
echo "  2. Check init containers: kubectl logs june-idp-xxx-xxx -n june-services -c setup-wallet"
echo "  3. Check Oracle test: kubectl logs june-idp-xxx-xxx -n june-services -c test-oracle"
echo "  4. Wait for ready: kubectl wait --for=condition=available deployment/june-idp -n june-services --timeout=1200s"
echo "  5. Get LoadBalancer IP: kubectl get svc june-idp-lb -n june-services"
echo ""
echo "🔧 If issues occur:"
echo "  - Check logs: kubectl logs deployment/june-idp -n june-services"
echo "  - Check wallet mount: kubectl exec -it deployment/june-idp -n june-services -- ls -la /opt/oracle/wallet/"
echo "  - Check Oracle connectivity: kubectl exec -it deployment/june-idp -n june-services -- nc -zv adb.us-ashburn-1.oraclecloud.com 1522"

log "✅ IDP deployment script completed!"