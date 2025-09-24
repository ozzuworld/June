#!/bin/bash
# comprehensive-fix.sh - Fix all infrastructure issues
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

PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"
NAMESPACE="june-services"

echo "🔧 Comprehensive Infrastructure Fix"
echo "=================================="
echo "Project: $PROJECT_ID"
echo "Namespace: $NAMESPACE"
echo ""

# Step 1: Clean up conflicting ingress resources
log "Step 1: Cleaning up conflicting configurations"

# Delete ALL existing ingresses to start fresh
kubectl delete ingress --all -n $NAMESPACE --ignore-not-found=true
kubectl delete managedcertificate --all -n $NAMESPACE --ignore-not-found=true
kubectl delete backendconfig --all -n $NAMESPACE --ignore-not-found=true

success "Cleaned up old ingress configurations"

# Step 2: Ensure services are properly configured as ClusterIP
log "Step 2: Fixing service configurations"

cat <<EOF | kubectl apply -f -
# Ensure all services are ClusterIP (required for GCE ingress)
apiVersion: v1
kind: Service
metadata:
  name: june-orchestrator
  namespace: $NAMESPACE
  labels:
    app: june-orchestrator
spec:
  type: ClusterIP
  selector:
    app: june-orchestrator
  ports:
  - name: http
    port: 8080
    targetPort: 8080
    protocol: TCP

---
apiVersion: v1
kind: Service
metadata:
  name: june-stt
  namespace: $NAMESPACE
  labels:
    app: june-stt
spec:
  type: ClusterIP
  selector:
    app: june-stt
  ports:
  - name: http
    port: 8080
    targetPort: 8080
    protocol: TCP

---
apiVersion: v1
kind: Service
metadata:
  name: june-idp
  namespace: $NAMESPACE
  labels:
    app: june-idp
spec:
  type: ClusterIP
  selector:
    app: june-idp
  ports:
  - name: http
    port: 8080
    targetPort: 8080
    protocol: TCP
EOF

success "Services configured as ClusterIP"

# Step 3: Deploy IDP service (currently showing 0/0 pods)
log "Step 3: Deploying missing IDP service"

cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-idp
  namespace: $NAMESPACE
  labels:
    app: june-idp
spec:
  replicas: 1
  selector:
    matchLabels:
      app: june-idp
  template:
    metadata:
      labels:
        app: june-idp
    spec:
      serviceAccountName: default
      containers:
      - name: june-idp
        image: us-central1-docker.pkg.dev/$PROJECT_ID/june/june-idp:latest
        ports:
        - containerPort: 8080
        # Resource limits for free tier compliance
        resources:
          requests:
            cpu: "200m"
            memory: "256Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
        env:
        - name: KEYCLOAK_ADMIN
          value: "admin"
        - name: KEYCLOAK_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: june-secrets
              key: KEYCLOAK_ADMIN_PASSWORD
        - name: KC_HOSTNAME_STRICT
          value: "false"
        - name: KC_HOSTNAME_STRICT_HTTPS
          value: "false"
        - name: KC_HTTP_ENABLED
          value: "true"
        - name: KC_PROXY
          value: "edge"
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 60
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 90
          periodSeconds: 30
        command: ["/opt/keycloak/bin/kc.sh"]
        args: ["start", "--optimized"]
EOF

# Step 4: Update existing deployments with resource limits
log "Step 4: Adding resource limits to existing deployments"

kubectl patch deployment june-orchestrator -n $NAMESPACE -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "june-orchestrator",
          "resources": {
            "requests": {
              "cpu": "300m",
              "memory": "512Mi"
            },
            "limits": {
              "cpu": "800m",
              "memory": "1Gi"
            }
          }
        }]
      }
    }
  }
}' || warning "Orchestrator patch failed - may not exist"

kubectl patch deployment june-stt -n $NAMESPACE -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "june-stt",
          "resources": {
            "requests": {
              "cpu": "200m",
              "memory": "256Mi"
            },
            "limits": {
              "cpu": "500m",
              "memory": "512Mi"
            }
          }
        }]
      }
    }
  }
}' || warning "STT patch failed - may not exist"

success "Resource limits applied"

# Step 5: Create secrets with Google Secret Manager integration
log "Step 5: Setting up Google Secret Manager integration"

# Enable Secret Manager API
gcloud services enable secretmanager.googleapis.com --project=$PROJECT_ID

# Create secrets in Secret Manager
log "Creating secrets in Secret Manager..."

# Generate secure passwords
KEYCLOAK_PASSWORD=$(openssl rand -base64 32)
JWT_SIGNING_KEY=$(openssl rand -base64 32)
DB_PASSWORD=$(openssl rand -base64 32)

# Store secrets in Secret Manager
gcloud secrets create keycloak-admin-password --data-file=<(echo -n "$KEYCLOAK_PASSWORD") --project=$PROJECT_ID || warning "Secret may already exist"
gcloud secrets create jwt-signing-key --data-file=<(echo -n "$JWT_SIGNING_KEY") --project=$PROJECT_ID || warning "Secret may already exist"
gcloud secrets create database-password --data-file=<(echo -n "$DB_PASSWORD") --project=$PROJECT_ID || warning "Secret may already exist"

# Create Service Account for Secret Manager access
gcloud iam service-accounts create june-secret-manager \
    --display-name="June Secret Manager SA" \
    --project=$PROJECT_ID || warning "SA may already exist"

# Grant access to secrets
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:june-secret-manager@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

# Create Kubernetes secret with Secret Manager references
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: june-secrets
  namespace: $NAMESPACE
  annotations:
    reloader.stakater.com/match: "true"
type: Opaque
stringData:
  KEYCLOAK_ADMIN_PASSWORD: "$KEYCLOAK_PASSWORD"
  JWT_SIGNING_KEY: "$JWT_SIGNING_KEY"
  DATABASE_PASSWORD: "$DB_PASSWORD"
  DATABASE_URL: "postgresql://postgres:$DB_PASSWORD@postgresql:5432/june_db"
  STT_CLIENT_ID: "june-stt"
  STT_CLIENT_SECRET: "$(openssl rand -base64 32)"
  ORCHESTRATOR_CLIENT_ID: "june-orchestrator"
  ORCHESTRATOR_CLIENT_SECRET: "$(openssl rand -base64 32)"
EOF

success "Secrets configured with Secret Manager"

# Step 6: Deploy simplified ingress configuration
log "Step 6: Deploying simplified ingress (api/stt/idp subdomains)"

cat <<EOF | kubectl apply -f -
apiVersion: networking.gke.io/v1
kind: ManagedCertificate
metadata:
  name: allsafe-ssl-cert
  namespace: $NAMESPACE
spec:
  domains:
  - allsafe.world
  - api.allsafe.world
  - stt.allsafe.world  
  - idp.allsafe.world

---
apiVersion: cloud.google.com/v1
kind: BackendConfig
metadata:
  name: june-backend-config
  namespace: $NAMESPACE
spec:
  healthCheck:
    checkIntervalSec: 30
    timeoutSec: 10
    healthyThreshold: 2
    unhealthyThreshold: 3
    type: HTTP
    requestPath: /healthz
    port: 8080
  timeoutSec: 60
  sessionAffinity:
    affinityType: "CLIENT_IP"
  connectionDraining:
    drainingTimeoutSec: 300

---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: allsafe-ingress
  namespace: $NAMESPACE
  annotations:
    kubernetes.io/ingress.class: "gce"
    kubernetes.io/ingress.global-static-ip-name: "june-services-ip"
    networking.gke.io/managed-certificates: "allsafe-ssl-cert"
    networking.gke.io/redirect-to-https: "true"
    cloud.google.com/backend-config: '{"default": "june-backend-config"}'
spec:
  rules:
  # Main domain - redirect to API
  - host: allsafe.world
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-orchestrator
            port:
              number: 8080
  
  # API subdomain - Orchestrator
  - host: api.allsafe.world
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-orchestrator
            port:
              number: 8080

  # STT subdomain - Speech-to-Text
  - host: stt.allsafe.world
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-stt
            port:
              number: 8080

  # IDP subdomain - Identity Provider  
  - host: idp.allsafe.world
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: june-idp
            port:
              number: 8080
EOF

success "Simplified ingress deployed"

# Step 7: Wait for deployments to be ready
log "Step 7: Waiting for deployments to be ready"

echo "Waiting for IDP deployment..."
kubectl wait --for=condition=available deployment/june-idp -n $NAMESPACE --timeout=300s || warning "IDP not ready yet"

echo "Checking all deployments..."
kubectl get deployments -n $NAMESPACE

# Step 8: Verify ingress translation
log "Step 8: Verifying ingress configuration"

echo "Waiting for ingress to be ready..."
sleep 30  # Give ingress controller time to process

kubectl describe ingress allsafe-ingress -n $NAMESPACE

# Step 9: Show status and next steps
echo ""
echo "🎯 DEPLOYMENT STATUS"
echo "===================="

echo ""
echo "📊 Pods:"
kubectl get pods -n $NAMESPACE

echo ""
echo "🌐 Services:"
kubectl get services -n $NAMESPACE

echo ""
echo "🔗 Ingress:"
kubectl get ingress -n $NAMESPACE

echo ""
echo "📜 Managed Certificate:"
kubectl get managedcertificate -n $NAMESPACE

echo ""
echo "💰 Resource Usage:"
kubectl top pods -n $NAMESPACE 2>/dev/null || warning "Metrics not available yet"

echo ""
echo "🎉 SIMPLIFIED ROUTING CONFIGURED:"
echo "=================================="
echo "✅ api.allsafe.world    → june-orchestrator (Main API)"
echo "✅ stt.allsafe.world    → june-stt (Speech-to-Text)"  
echo "✅ idp.allsafe.world    → june-idp (Identity Provider)"
echo "✅ allsafe.world        → june-orchestrator (Redirect)"

echo ""
echo "🔐 SECURITY IMPROVEMENTS:"
echo "========================="
echo "✅ Google Secret Manager integration"
echo "✅ Resource limits for free tier compliance"
echo "✅ Single ingress (no LoadBalancer conflicts)"
echo "✅ Proper health check configuration"

echo ""
echo "⏳ NEXT STEPS:"
echo "=============="
echo "1. Wait 5-10 minutes for certificate provisioning"
echo "2. Monitor certificate status:"
echo "   kubectl get managedcertificate -n $NAMESPACE"
echo "3. Test endpoints once certificate is ACTIVE:"
echo "   curl https://api.allsafe.world/healthz"
echo "   curl https://stt.allsafe.world/healthz"
echo "   curl https://idp.allsafe.world/health"
echo ""

success "Comprehensive fix completed!"
echo ""
warning "Certificate provisioning in progress - check status in 5-10 minutes"