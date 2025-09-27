#!/bin/bash
# deploy-clean-orchestrator.sh
# Deploy the clean June orchestrator to Google Kubernetes Engine

set -euo pipefail

echo "🚀 Deploying Clean June Orchestrator"
echo "===================================="

# Configuration
PROJECT_ID="${PROJECT_ID:-main-buffer-469817-v7}"
REGION="${REGION:-us-central1}"
CLUSTER_NAME="${CLUSTER_NAME:-june-unified-cluster}"
NAMESPACE="${NAMESPACE:-june-services}"
ARTIFACT_REGISTRY="us-central1-docker.pkg.dev/${PROJECT_ID}/june"

# Check prerequisites
echo "🔍 Checking prerequisites..."

# Check if gcloud is configured
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n1 > /dev/null; then
    echo "❌ gcloud not authenticated. Run: gcloud auth login"
    exit 1
fi

# Check if kubectl can access cluster
if ! kubectl cluster-info > /dev/null 2>&1; then
    echo "⚠️ kubectl not connected to cluster. Getting credentials..."
    gcloud container clusters get-credentials $CLUSTER_NAME \
        --region=$REGION \
        --project=$PROJECT_ID
fi

# Check if namespace exists
if ! kubectl get namespace $NAMESPACE > /dev/null 2>&1; then
    echo "📦 Creating namespace $NAMESPACE..."
    kubectl create namespace $NAMESPACE
fi

echo "✅ Prerequisites OK"

# Step 1: Build the clean orchestrator
echo ""
echo "🐳 Step 1: Building clean orchestrator..."

cd June/services/june-orchestrator

# Generate build metadata
BUILD_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
GIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
IMAGE_TAG="clean-v3-$(date +%s)"
FULL_IMAGE="${ARTIFACT_REGISTRY}/june-orchestrator:${IMAGE_TAG}"

echo "🏷️ Building image: $FULL_IMAGE"

# Configure Docker for Artifact Registry
gcloud auth configure-docker $REGION-docker.pkg.dev --quiet

# Build the image
docker build \
    --build-arg GIT_SHA=$GIT_SHA \
    --build-arg BUILD_TIME=$BUILD_TIME \
    -t "$FULL_IMAGE" \
    -t "${ARTIFACT_REGISTRY}/june-orchestrator:latest" \
    .

echo "✅ Image built successfully"

# Step 2: Push to registry
echo ""
echo "📤 Step 2: Pushing to Artifact Registry..."

docker push "$FULL_IMAGE"
docker push "${ARTIFACT_REGISTRY}/june-orchestrator:latest"

echo "✅ Image pushed successfully"

# Step 3: Ensure Gemini API key secret exists
echo ""
echo "🔑 Step 3: Checking Gemini API key secret..."

if kubectl get secret june-secrets -n $NAMESPACE > /dev/null 2>&1; then
    echo "✅ Secret 'june-secrets' exists"
else
    echo "⚠️ Secret 'june-secrets' not found"
    
    # Try to read from .env file
    if [ -f ".env" ]; then
        GEMINI_KEY=$(grep "^GEMINI_API_KEY=" .env | cut -d'=' -f2 | tr -d '"' || echo "")
        
        if [ ! -z "$GEMINI_KEY" ]; then
            echo "📋 Creating secret from .env file..."
            kubectl create secret generic june-secrets \
                --from-literal=gemini-api-key="$GEMINI_KEY" \
                -n $NAMESPACE
            echo "✅ Secret created"
        else
            echo "❌ No GEMINI_API_KEY found in .env file"
            echo "   Please set your Gemini API key:"
            echo "   kubectl create secret generic june-secrets --from-literal=gemini-api-key='YOUR_API_KEY' -n $NAMESPACE"
            exit 1
        fi
    else
        echo "❌ No .env file found and no secret exists"
        echo "   Please create the secret manually:"
        echo "   kubectl create secret generic june-secrets --from-literal=gemini-api-key='YOUR_API_KEY' -n $NAMESPACE"
        exit 1
    fi
fi

# Step 4: Deploy to Kubernetes
echo ""
echo "☸️  Step 4: Deploying to Kubernetes..."

# Create/update deployment
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-orchestrator
  namespace: $NAMESPACE
  labels:
    app: june-orchestrator
    version: "3.0.0"
spec:
  replicas: 1
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  selector:
    matchLabels:
      app: june-orchestrator
  template:
    metadata:
      labels:
        app: june-orchestrator
        version: "3.0.0"
    spec:
      containers:
        - name: orchestrator
          image: $FULL_IMAGE
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
          env:
            - name: GEMINI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: june-secrets
                  key: gemini-api-key
            - name: ENVIRONMENT
              value: "production"
            - name: LOG_LEVEL
              value: "INFO"
          resources:
            requests:
              cpu: "200m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
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
          startupProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
            failureThreshold: 20
---
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
      port: 80
      targetPort: 8080
      protocol: TCP
EOF

echo "✅ Deployment manifest applied"

# Step 5: Wait for rollout
echo ""
echo "⏳ Step 5: Waiting for deployment to complete..."

kubectl rollout status deployment/june-orchestrator -n $NAMESPACE --timeout=300s

echo "✅ Deployment completed successfully"

# Step 6: Verify deployment
echo ""
echo "🧪 Step 6: Verifying deployment..."

echo "📋 Checking pods..."
kubectl get pods -n $NAMESPACE -l app=june-orchestrator

echo ""
echo "🌐 Testing endpoints..."

# Wait a bit for the pod to be fully ready
sleep 10

POD_NAME=$(kubectl get pods -n $NAMESPACE -l app=june-orchestrator -o jsonpath='{.items[0].metadata.name}')

echo "Testing health endpoint..."
kubectl exec -n $NAMESPACE $POD_NAME -- curl -s http://localhost:8080/healthz | head -c 200 || echo "Failed"

echo ""
echo "Testing debug endpoint..."
kubectl exec -n $NAMESPACE $POD_NAME -- curl -s http://localhost:8080/debug/status | head -c 200 || echo "Failed"

echo ""
echo "Testing chat endpoint..."
kubectl exec -n $NAMESPACE $POD_NAME -- curl -s -X POST http://localhost:8080/debug/test-chat | head -c 200 || echo "Failed"

echo ""
echo "=================================="
echo "🎉 DEPLOYMENT COMPLETE!"
echo "=================================="
echo ""
echo "✅ Clean orchestrator deployed successfully"
echo ""
echo "📊 Deployment Info:"
echo "   Image: $FULL_IMAGE"
echo "   Namespace: $NAMESPACE"
echo "   Pod: $POD_NAME"
echo ""
echo "🌐 External URL (if ingress configured):"
echo "   https://api.allsafe.world"
echo ""
echo "🔧 Useful commands:"
echo "   # Check logs"
echo "   kubectl logs -n $NAMESPACE deployment/june-orchestrator -f"
echo ""
echo "   # Check status"
echo "   kubectl get pods -n $NAMESPACE -l app=june-orchestrator"
echo ""
echo "   # Test endpoints"
echo "   curl https://api.allsafe.world/healthz"
echo "   curl https://api.allsafe.world/debug/status"
echo "   curl -X POST https://api.allsafe.world/debug/test-chat"