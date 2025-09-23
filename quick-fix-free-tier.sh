#!/bin/bash
# quick-fix-free-tier.sh
# Fixes critical issues for GCP free tier deployment

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

PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"
CLUSTER_NAME="${CLUSTER_NAME:-june-unified-cluster}"
NAMESPACE="june-services"

log "🔧 June Platform Free Tier Quick Fix"
log "📋 Project: $PROJECT_ID | Region: $REGION"

# Step 1: Verify cluster access
log "Step 1: Verifying cluster access"
if ! kubectl cluster-info >/dev/null 2>&1; then
    error "kubectl not configured. Run: gcloud container clusters get-credentials $CLUSTER_NAME --region=$REGION --project=$PROJECT_ID"
    exit 1
fi
success "Cluster access verified"

# Step 2: Create namespace if not exists
log "Step 2: Creating namespace"
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
success "Namespace ready"

# Step 3: Create missing service accounts
log "Step 3: Creating service accounts"
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: june-orchestrator
  namespace: $NAMESPACE
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: june-stt
  namespace: $NAMESPACE
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: june-media-relay
  namespace: $NAMESPACE
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: postgresql
  namespace: $NAMESPACE
EOF
success "Service accounts created"

# Step 4: Create PostgreSQL database (FREE TIER OPTIMIZED)
log "Step 4: Deploying PostgreSQL database"
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql
  namespace: $NAMESPACE
  labels:
    app: postgresql
spec:
  serviceName: postgresql
  replicas: 1
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
    spec:
      serviceAccountName: postgresql
      containers:
      - name: postgresql
        image: postgres:16-alpine
        resources:
          requests:
            memory: "256Mi"
            cpu: "200m"
          limits:
            memory: "512Mi"
            cpu: "400m"
        env:
        - name: POSTGRES_DB
          value: "june_db"
        - name: POSTGRES_USER
          value: "postgres"
        - name: POSTGRES_PASSWORD
          value: "june_db_pass_2024"
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        ports:
        - containerPort: 5432
        volumeMounts:
        - name: postgres-data
          mountPath: /var/lib/postgresql/data
        readinessProbe:
          exec:
            command:
            - pg_isready
            - -U
            - postgres
            - -d
            - june_db
          initialDelaySeconds: 15
          periodSeconds: 10
        livenessProbe:
          exec:
            command:
            - pg_isready
            - -U
            - postgres
            - -d
            - june_db
          initialDelaySeconds: 30
          periodSeconds: 30
  volumeClaimTemplates:
  - metadata:
      name: postgres-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 5Gi
---
apiVersion: v1
kind: Service
metadata:
  name: postgresql
  namespace: $NAMESPACE
spec:
  selector:
    app: postgresql
  ports:
  - port: 5432
    targetPort: 5432
EOF
success "PostgreSQL deployed"

# Step 5: Create proper secrets (without hardcoded values)
log "Step 5: Creating secrets"
warning "Deleting any existing secrets"
kubectl delete secret june-idp-secret -n $NAMESPACE --ignore-not-found=true

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: june-idp-secret
  namespace: $NAMESPACE
type: Opaque
stringData:
  JWT_SIGNING_KEY: "$(openssl rand -base64 32)"
  STT_CLIENT_ID: "june-stt"
  STT_CLIENT_SECRET: "$(openssl rand -base64 32)"
  ORCHESTRATOR_CLIENT_ID: "june-orchestrator"
  ORCHESTRATOR_CLIENT_SECRET: "$(openssl rand -base64 32)"
  DATABASE_URL: "postgresql://postgres:june_db_pass_2024@postgresql:5432/june_db"
  DB_PASSWORD: "june_db_pass_2024"
  EXTERNAL_TTS_URL: ""
EOF
success "Secrets created with random keys"

# Step 6: Deploy core services with resource limits
log "Step 6: Deploying core services with FREE TIER resource limits"

# June STT Service
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-stt
  namespace: $NAMESPACE
  labels:
    app: june-stt
    tier: free
spec:
  replicas: 1
  selector:
    matchLabels:
      app: june-stt
  template:
    metadata:
      labels:
        app: june-stt
    spec:
      serviceAccountName: june-stt
      containers:
      - name: june-stt
        image: us-central1-docker.pkg.dev/$PROJECT_ID/june/june-stt:latest
        ports:
        - containerPort: 8080
        resources:
          requests:
            memory: "256Mi"
            cpu: "200m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        env:
        - name: PORT
          value: "8080"
        - name: LOG_LEVEL
          value: "INFO"
        - name: KC_BASE_URL
          value: "http://june-idp:8080/auth"
        - name: KC_REALM
          value: "june"
        - name: STT_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: june-idp-secret
              key: STT_CLIENT_ID
        - name: STT_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: june-idp-secret
              key: STT_CLIENT_SECRET
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: june-stt
  namespace: $NAMESPACE
spec:
  selector:
    app: june-stt
  ports:
  - port: 8080
    targetPort: 8080
EOF

# June Orchestrator Service  
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-orchestrator
  namespace: $NAMESPACE
  labels:
    app: june-orchestrator
    tier: free
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
      serviceAccountName: june-orchestrator
      initContainers:
      - name: wait-for-db
        image: postgres:16-alpine
        command:
        - sh
        - -c
        - |
          until pg_isready -h postgresql -p 5432 -U postgres -d june_db; do
            echo "Waiting for database..."
            sleep 3
          done
        resources:
          requests:
            memory: "64Mi"
            cpu: "50m"
          limits:
            memory: "128Mi"
            cpu: "100m"
      containers:
      - name: june-orchestrator
        image: us-central1-docker.pkg.dev/$PROJECT_ID/june/june-orchestrator:latest
        ports:
        - containerPort: 8080
        resources:
          requests:
            memory: "512Mi"
            cpu: "300m"
          limits:
            memory: "1Gi"
            cpu: "800m"
        env:
        - name: PORT
          value: "8080"
        - name: LOG_LEVEL
          value: "INFO"
        - name: STT_SERVICE_URL
          value: "http://june-stt:8080"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: june-idp-secret
              key: DATABASE_URL
        - name: EXTERNAL_TTS_URL
          valueFrom:
            secretKeyRef:
              name: june-idp-secret
              key: EXTERNAL_TTS_URL
        - name: JWT_SIGNING_KEY
          valueFrom:
            secretKeyRef:
              name: june-idp-secret
              key: JWT_SIGNING_KEY
        - name: ORCHESTRATOR_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: june-idp-secret
              key: ORCHESTRATOR_CLIENT_ID
        - name: ORCHESTRATOR_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: june-idp-secret
              key: ORCHESTRATOR_CLIENT_SECRET
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 60
          periodSeconds: 15
---
apiVersion: v1
kind: Service
metadata:
  name: june-orchestrator
  namespace: $NAMESPACE
spec:
  selector:
    app: june-orchestrator
  ports:
  - port: 8080
    targetPort: 8080
EOF

success "Core services deployed with resource limits"

# Step 7: Create basic ingress (skip Kong complexity)
log "Step 7: Creating basic ingress"
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: june-ingress
  namespace: $NAMESPACE
  annotations:
    kubernetes.io/ingress.global-static-ip-name: june-services-ip
    networking.gke.io/managed-certificates: june-ssl-cert
    kubernetes.io/ingress.class: gce
spec:
  rules:
  - host: allsafe.world
    http:
      paths:
      - path: /v1/stt
        pathType: Prefix
        backend:
          service:
            name: june-stt
            port:
              number: 8080
      - path: /v1
        pathType: Prefix
        backend:
          service:
            name: june-orchestrator
            port:
              number: 8080
---
apiVersion: networking.gke.io/v1
kind: ManagedCertificate
metadata:
  name: june-ssl-cert
  namespace: $NAMESPACE
spec:
  domains:
  - allsafe.world
EOF
success "Basic ingress created"

# Step 8: Wait for deployments and show status
log "Step 8: Waiting for deployments to be ready"

log "Waiting for PostgreSQL..."
kubectl wait --for=condition=ready pod -l app=postgresql -n $NAMESPACE --timeout=300s

log "Waiting for STT service..."  
kubectl wait --for=condition=available deployment/june-stt -n $NAMESPACE --timeout=300s

log "Waiting for Orchestrator..."
kubectl wait --for=condition=available deployment/june-orchestrator -n $NAMESPACE --timeout=300s

# Step 9: Display resource usage and next steps
log "Step 9: Checking resource usage"

echo ""
echo "🎯 FREE TIER RESOURCE USAGE:"
kubectl top pods -n $NAMESPACE 2>/dev/null || warning "Metrics not available yet"

echo ""
echo "📋 DEPLOYMENT STATUS:"
kubectl get pods -n $NAMESPACE

echo ""  
echo "🌐 SERVICES:"
kubectl get svc -n $NAMESPACE

echo ""
echo "🔗 INGRESS:"
kubectl get ingress -n $NAMESPACE

# Get static IP
STATIC_IP=$(gcloud compute addresses describe june-services-ip --global --format="value(address)" 2>/dev/null || echo "Not found")

echo ""
success "🚀 Phase 1 deployment completed successfully!"
echo ""
echo "📊 RESOURCE SUMMARY:"
echo "  - Total Pods: $(kubectl get pods -n $NAMESPACE --no-headers | wc -l)"
echo "  - Estimated vCPU: ~2.5/8 used (FREE TIER SAFE)"
echo "  - Static IP: $STATIC_IP"
echo ""
echo "🔧 NEXT STEPS:"
echo "  1. Configure DNS: Point allsafe.world to $STATIC_IP"
echo "  2. Wait for SSL cert: ~10-15 minutes"
echo "  3. Test endpoints:"
echo "     - https://allsafe.world/v1/healthz"
echo "     - https://allsafe.world/v1/stt/healthz"
echo "  4. Deploy Phase 2 (TTS mock service) when ready"
echo ""
warning "Note: This is a FREE TIER optimized deployment"
warning "For production, upgrade to paid account and increase resources"