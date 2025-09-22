#!/bin/bash
# postgresql-keycloak-migration.sh - Complete migration from Oracle to PostgreSQL

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

log "🐘 Complete PostgreSQL Migration for Keycloak (Free Tier Optimized)"
log "This will replace Oracle with PostgreSQL using Keycloak's recommended configuration"

# Step 1: Clean up Oracle deployment
log "Step 1: Removing Oracle-based Keycloak deployment"

# Remove Oracle Keycloak deployment
kubectl delete deployment june-idp -n june-services --ignore-not-found=true
kubectl delete svc june-idp june-idp-lb -n june-services --ignore-not-found=true
kubectl delete configmap keycloak-config -n june-services --ignore-not-found=true

# Keep the Oracle secrets in case you want to switch back later
warning "Oracle secrets kept for potential rollback (oracle-wallet, oracle-credentials)"

success "Oracle Keycloak deployment removed"

# Step 2: Deploy PostgreSQL with Keycloak-optimized configuration
log "Step 2: Deploying PostgreSQL with Keycloak recommended settings"

cat > postgresql-keycloak-setup.yaml << 'EOF'
# PostgreSQL deployment optimized for Keycloak (Free Tier)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgresql
  namespace: june-services
  labels:
    app: postgresql
    component: database
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
        component: database
    spec:
      containers:
      - name: postgresql
        image: postgres:15-alpine
        ports:
        - name: postgres
          containerPort: 5432
          protocol: TCP
        
        # Environment variables for Keycloak-optimized PostgreSQL
        env:
        - name: POSTGRES_DB
          value: keycloak
        - name: POSTGRES_USER
          value: keycloak
        - name: POSTGRES_PASSWORD
          value: keycloak_secure_password_123
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        # PostgreSQL performance settings for Keycloak
        - name: POSTGRES_INITDB_ARGS
          value: "--encoding=UTF8 --locale=C"
        
        # Resource limits optimized for free tier
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "300m"
        
        # Volume for data persistence (emptyDir for free tier)
        volumeMounts:
        - name: postgres-data
          mountPath: /var/lib/postgresql/data
        
        # Health checks
        livenessProbe:
          exec:
            command:
            - pg_isready
            - -U
            - keycloak
            - -d
            - keycloak
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
        
        readinessProbe:
          exec:
            command:
            - pg_isready
            - -U
            - keycloak
            - -d
            - keycloak
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
      
      volumes:
      - name: postgres-data
        emptyDir: {}
        # Note: For production, use PersistentVolumeClaim instead:
        # persistentVolumeClaim:
        #   claimName: postgres-pvc

---
apiVersion: v1
kind: Service
metadata:
  name: postgresql
  namespace: june-services
  labels:
    app: postgresql
spec:
  type: ClusterIP
  ports:
  - name: postgres
    port: 5432
    targetPort: 5432
    protocol: TCP
  selector:
    app: postgresql

---
# Keycloak configuration for PostgreSQL
apiVersion: v1
kind: ConfigMap
metadata:
  name: keycloak-postgres-config
  namespace: june-services
data:
  # Keycloak PostgreSQL configuration (recommended settings)
  KC_DB: "postgres"
  KC_DB_URL: "jdbc:postgresql://postgresql:5432/keycloak"
  KC_DB_USERNAME: "keycloak"
  KC_DB_SCHEMA: "public"
  # Performance and connection settings
  KC_DB_POOL_INITIAL_SIZE: "5"
  KC_DB_POOL_MIN_SIZE: "5"
  KC_DB_POOL_MAX_SIZE: "20"
  # Keycloak server configuration
  KC_HOSTNAME_STRICT: "false"
  KC_HTTP_ENABLED: "true"
  KC_HEALTH_ENABLED: "true"
  KC_METRICS_ENABLED: "true"
  KC_TRANSACTION_XA_ENABLED: "false"
  KC_CACHE: "local"
  KC_LOG_LEVEL: "INFO"
  KC_PROXY: "edge"
  # JVM settings optimized for free tier
  JAVA_OPTS_APPEND: "-XX:MaxRAMPercentage=75.0 -XX:+UseContainerSupport -XX:+UseG1GC -XX:MaxGCPauseMillis=100 -Dkeycloak.connectionsInfinispan.default.clustered=false"

---
# Keycloak secrets
apiVersion: v1
kind: Secret
metadata:
  name: keycloak-postgres-secrets
  namespace: june-services
type: Opaque
stringData:
  KC_DB_PASSWORD: "keycloak_secure_password_123"
  KEYCLOAK_ADMIN: "admin"
  KEYCLOAK_ADMIN_PASSWORD: "admin123456"

---
# Keycloak deployment with PostgreSQL
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-idp-postgres
  namespace: june-services
  labels:
    app: june-idp-postgres
    component: identity-provider
spec:
  replicas: 1
  selector:
    matchLabels:
      app: june-idp-postgres
  template:
    metadata:
      labels:
        app: june-idp-postgres
        component: identity-provider
    spec:
      # Init container to wait for PostgreSQL
      initContainers:
      - name: wait-for-postgres
        image: postgres:15-alpine
        command: ['sh', '-c']
        args:
          - |
            echo "🐘 Waiting for PostgreSQL to be ready..."
            until pg_isready -h postgresql -p 5432 -U keycloak -d keycloak; do
              echo "PostgreSQL not ready, waiting 5 seconds..."
              sleep 5
            done
            echo "✅ PostgreSQL is ready!"
            echo "📊 PostgreSQL connection test:"
            PGPASSWORD=keycloak_secure_password_123 psql -h postgresql -U keycloak -d keycloak -c "SELECT version();" || echo "Connection test failed but continuing..."
        resources:
          requests:
            memory: "64Mi"
            cpu: "50m"
          limits:
            memory: "128Mi"
            cpu: "100m"
      
      containers:
      - name: keycloak
        image: quay.io/keycloak/keycloak:23.0.0
        args:
          - "start"
          - "--db=postgres"
          - "--http-enabled=true"
          - "--hostname-strict=false"
          - "--proxy=edge"
          - "--transaction-xa-enabled=false"
          - "--cache=local"
          - "--health-enabled=true"
          - "--metrics-enabled=true"
          - "--optimized"
        
        ports:
        - name: http
          containerPort: 8080
          protocol: TCP
        
        # Environment from ConfigMap
        envFrom:
        - configMapRef:
            name: keycloak-postgres-config
        
        # Environment from Secrets
        env:
        - name: KC_DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: keycloak-postgres-secrets
              key: KC_DB_PASSWORD
        - name: KEYCLOAK_ADMIN
          valueFrom:
            secretKeyRef:
              name: keycloak-postgres-secrets
              key: KEYCLOAK_ADMIN
        - name: KEYCLOAK_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: keycloak-postgres-secrets
              key: KEYCLOAK_ADMIN_PASSWORD
        
        # Resource limits optimized for free tier
        resources:
          requests:
            memory: "512Mi"
            cpu: "200m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        
        # Health checks with appropriate timeouts for PostgreSQL
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 60
          periodSeconds: 30
          timeoutSeconds: 10
          failureThreshold: 5
        
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 10
        
        startupProbe:
          httpGet:
            path: /health/started
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 15
          timeoutSeconds: 10
          failureThreshold: 20  # Up to 5 minutes

---
# Keycloak service
apiVersion: v1
kind: Service
metadata:
  name: june-idp-postgres
  namespace: june-services
  labels:
    app: june-idp-postgres
spec:
  type: ClusterIP
  ports:
  - name: http
    port: 8080
    targetPort: 8080
    protocol: TCP
  selector:
    app: june-idp-postgres

---
# LoadBalancer for external access
apiVersion: v1
kind: Service
metadata:
  name: june-idp-postgres-lb
  namespace: june-services
  labels:
    app: june-idp-postgres
spec:
  type: LoadBalancer
  ports:
  - name: http
    port: 80
    targetPort: 8080
    protocol: TCP
  selector:
    app: june-idp-postgres
EOF

success "PostgreSQL manifests created with Keycloak recommended settings"

# Step 3: Deploy PostgreSQL and Keycloak
log "Step 3: Deploying PostgreSQL and Keycloak"
kubectl apply -f postgresql-keycloak-setup.yaml

success "PostgreSQL and Keycloak deployed"

# Step 4: Monitor deployment
log "Step 4: Monitoring deployment progress"

echo ""
log "📊 Deployment timeline (PostgreSQL is much faster than Oracle!):"
log "  0-30 seconds: PostgreSQL starts"
log "  30-60 seconds: Keycloak init container waits for PostgreSQL"
log "  1-3 minutes: Keycloak starts and creates schema"
log "  3-5 minutes: Ready for use!"
log ""
log "Compare to Oracle: 15-30 minutes with complex wallet setup"

sleep 10

# Check PostgreSQL first
log "🐘 Checking PostgreSQL status:"
kubectl get pods -n june-services | grep postgres

# Check Keycloak
log "🔐 Checking Keycloak status:"
kubectl get pods -n june-services | grep june-idp-postgres

echo ""
log "📋 All services status:"
kubectl get pods -n june-services

echo ""
log "🔍 Watching PostgreSQL and Keycloak startup (press Ctrl+C to stop)..."
kubectl get pods -n june-services -w --timeout=300s || true

# Clean up
rm -f postgresql-keycloak-setup.yaml

echo ""
success "✅ PostgreSQL migration initiated!"
echo ""
echo "🎯 Next steps:"
echo "1. Wait for pods to show 1/1 Running (2-5 minutes)"
echo "2. Get external IP: kubectl get svc june-idp-postgres-lb -n june-services"
echo "3. Test health: curl http://EXTERNAL-IP/health/ready"
echo "4. Access admin: kubectl port-forward svc/june-idp-postgres 8080:8080 -n june-services"
echo "5. Open browser: http://localhost:8080 (admin/admin123456)"
echo ""
echo "🔧 Monitoring commands:"
echo "- Logs: kubectl logs -f deployment/june-idp-postgres -n june-services"
echo "- Status: kubectl get pods -n june-services"
echo "- PostgreSQL test: kubectl exec -it deployment/postgresql -n june-services -- psql -U keycloak -d keycloak -c '\\dt'"
echo ""
echo "💡 Benefits of PostgreSQL:"
echo "✅ 5-10x faster startup than Oracle"
echo "✅ No wallet/SSL complexities"
echo "✅ Better resource efficiency for free tier"
echo "✅ Standard Keycloak configuration"
echo "✅ Easier troubleshooting and maintenance"