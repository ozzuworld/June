#!/bin/bash
# deploy-tts-fix.sh - Fix TTS wiring for low-latency architecture

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
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/june"
NAMESPACE="june-services"

log "🔧 Fixing TTS wiring for low-latency architecture"

# Step 1: Update secrets with TTS configuration
log "Step 1: Updating secrets with TTS client credentials"

kubectl patch secret june-idp-secret -n $NAMESPACE --type='merge' -p='{
  "stringData": {
    "TTS_CLIENT_ID": "june-tts",
    "TTS_CLIENT_SECRET": "Kj8Pn2Xm9Qr4Yt6Wb3Zc7Vf5Hg1Jk8L",
    "TTS_BASE_URL": "http://june-tts:80",
    "EXTERNAL_TTS_URL": "https://tts.allsafe.world"
  }
}'

success "Secrets updated"

# Step 2: Build and deploy TTS service
log "Step 2: Building and deploying TTS service"

cd June/services/june-tts || error "Cannot find TTS service directory"

# Build TTS image
log "Building TTS container..."
docker build -t "${REGISTRY}/june-tts:latest" .
docker push "${REGISTRY}/june-tts:latest"
success "TTS image built and pushed"

cd ../../..

# Step 3: Deploy TTS service
log "Step 3: Deploying TTS service to Kubernetes"

# Create TTS deployment
cat > /tmp/tts-deployment.yaml << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-tts
  namespace: june-services
  labels:
    app: june-tts
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: june-tts
  template:
    metadata:
      labels:
        app: june-tts
    spec:
      containers:
        - name: app
          image: us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-tts:latest
          imagePullPolicy: Always
          ports:
            - containerPort: 8000
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
              ephemeral-storage: "512Mi"
            limits:
              cpu: "1"
              memory: "2Gi"
              ephemeral-storage: "2Gi"
          env:
            - name: OPENVOICE_CHECKPOINTS_V2
              value: "/models/openvoice/checkpoints_v2"
            - name: OPENVOICE_DEVICE
              value: "cpu"
            - name: CORS_ALLOW_ORIGINS
              value: "*"
            - name: MAX_FILE_SIZE
              value: "52428800"
            - name: MAX_TEXT_LEN
              value: "2000"
            - name: KEYCLOAK_URL
              value: "http://june-idp:8080"
            - name: KEYCLOAK_REALM
              value: "allsafe"
            - name: KEYCLOAK_CLIENT_ID
              value: "june-tts"
            - name: KEYCLOAK_CLIENT_SECRET
              valueFrom:
                secretKeyRef:
                  name: june-idp-secret
                  key: TTS_CLIENT_SECRET
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8000
            initialDelaySeconds: 60
            periodSeconds: 30
            timeoutSeconds: 10
      restartPolicy: Always

---
apiVersion: v1
kind: Service
metadata:
  name: june-tts
  namespace: june-services
  labels:
    app: june-tts
  annotations:
    cloud.google.com/neg: '{"ingress": true}'
    cloud.google.com/backend-config: '{"default":"june-backend-config"}'
spec:
  selector:
    app: june-tts
  ports:
    - name: http
      port: 80
      targetPort: 8000
  type: ClusterIP
EOF

kubectl apply -f /tmp/tts-deployment.yaml
success "TTS service deployed"

# Step 4: Update orchestrator to remove TTS proxy reference
log "Step 4: Updating orchestrator configuration"

kubectl patch deployment june-orchestrator -n $NAMESPACE -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "app",
          "env": [
            {"name": "TTS_BASE_URL", "valueFrom": {"secretKeyRef": {"name": "june-idp-secret", "key": "TTS_BASE_URL"}}},
            {"name": "EXTERNAL_TTS_URL", "valueFrom": {"secretKeyRef": {"name": "june-idp-secret", "key": "EXTERNAL_TTS_URL"}}},
            {"name": "OIDC_AUDIENCE", "value": "june-mobile-app"}
          ]
        }]
      }
    }
  }
}'

# Restart orchestrator to pick up changes
kubectl rollout restart deployment/june-orchestrator -n $NAMESPACE
success "Orchestrator updated"

# Step 5: Update ingress to include TTS subdomain
log "Step 5: Updating ingress for TTS access"

# Get current ingress and add TTS rule
kubectl patch ingress allsafe-ingress -n $NAMESPACE --type='merge' -p='{
  "spec": {
    "rules": [
      {
        "host": "tts.allsafe.world",
        "http": {
          "paths": [
            {
              "path": "/",
              "pathType": "Prefix",
              "backend": {
                "service": {
                  "name": "june-tts",
                  "port": {
                    "number": 80
                  }
                }
              }
            }
          ]
        }
      }
    ]
  }
}'

# Update managed certificate to include TTS domain
kubectl patch managedcertificate allsafe-ssl-cert -n $NAMESPACE --type='merge' -p='{
  "spec": {
    "domains": [
      "allsafe.world",
      "api.allsafe.world", 
      "stt.allsafe.world",
      "idp.allsafe.world",
      "tts.allsafe.world"
    ]
  }
}'

success "Ingress updated with TTS domain"

# Step 6: Wait for deployments
log "Step 6: Waiting for deployments to be ready"

kubectl rollout status deployment/june-tts -n $NAMESPACE --timeout=300s
kubectl rollout status deployment/june-orchestrator -n $NAMESPACE --timeout=300s

# Step 7: Test TTS service
log "Step 7: Testing TTS service"

# Wait for TTS pod to be ready
sleep 30

TTS_POD=$(kubectl get pods -n $NAMESPACE -l app=june-tts -o jsonpath='{.items[0].metadata.name}')
if [ -z "$TTS_POD" ]; then
    warning "No TTS pod found"
else
    log "Testing TTS pod: $TTS_POD"
    
    # Test health endpoint
    kubectl exec $TTS_POD -n $NAMESPACE -- curl -s http://localhost:8000/healthz || warning "TTS health check failed"
fi

# Step 8: Cleanup
rm -f /tmp/tts-deployment.yaml

# Step 9: Summary
echo ""
echo "=============================="
echo "TTS LOW-LATENCY SETUP COMPLETE"
echo "=============================="
echo ""
echo "✅ Architecture Summary:"
echo "  📱 Frontend → TTS Service (Direct, Low Latency)"
echo "  🤖 Frontend → Orchestrator (Text + TTS URL)"
echo "  🔗 TTS URL: https://tts.allsafe.world/tts/generate"
echo ""
echo "🔍 Next Steps:"
echo "  1. Update your frontend to use the new low-latency flow"
echo "  2. Test the integration:"
echo "     curl -X POST https://api.allsafe.world/v1/chat \\"
echo "          -H 'Authorization: Bearer YOUR_TOKEN' \\"
echo "          -H 'Content-Type: application/json' \\"
echo "          -d '{\"text\":\"Hello TTS test\"}'"
echo ""
echo "  3. The response will include 'tts' field with direct URL"
echo "  4. Frontend calls TTS directly for audio generation"
echo ""
echo "📊 Monitor with:"
echo "  kubectl logs deployment/june-tts -n $NAMESPACE -f"
echo "  kubectl logs deployment/june-orchestrator -n $NAMESPACE -f"
echo ""

success "🎉 TTS low-latency setup completed successfully!"

# Step 10: DNS reminder
echo ""
echo "🌐 DNS Configuration Required:"
echo "  Add A record: tts.allsafe.world → $(kubectl get ingress allsafe-ingress -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].ip}')"
echo ""