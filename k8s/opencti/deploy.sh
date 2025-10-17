#!/bin/bash
# File: k8s/opencti/deploy.sh
# OpenCTI deployment script - FIXED VERSION

set -e

echo "🚀 Starting OpenCTI deployment..."

# First, verify OpenSearch is running
echo "🔍 Step 1: Verifying OpenSearch cluster..."
chmod +x verify-opensearch.sh
./verify-opensearch.sh || {
    echo "❌ OpenSearch cluster verification failed!"
    echo "ℹ️ Please ensure OpenSearch is deployed and running in the default namespace"
    echo "ℹ️ Expected service: opensearch-cluster-master.default.svc.cluster.local:9200"
    exit 1
}

echo "📋 Step 2: Adding OpenCTI Helm repository..."
helm repo add opencti https://devops-ia.github.io/helm-opencti
helm repo update

echo "🛠️ Step 3: Deploying OpenCTI with fixed configuration..."
helm upgrade --install opencti opencti/opencti \
  --namespace opencti \
  --create-namespace \
  -f values.yaml \
  --timeout 15m \
  --wait

echo "✅ OpenCTI deployment initiated"
echo "🔍 Monitoring deployment status..."
echo "Run: kubectl get pods -n opencti -w"
echo "Check logs: kubectl logs -n opencti -l app.kubernetes.io/name=opencti"
echo "🌐 Access URL (once ready): https://opencti.ozzu.world"