#!/bin/bash
# File: k8s/opencti/verify-opensearch.sh
# Script to verify OpenSearch cluster is running before deploying OpenCTI

set -e

echo "🔍 Checking OpenSearch cluster status..."

# Check if OpenSearch pods are running
echo "📦 OpenSearch pods in default namespace:"
kubectl get pods -l app=opensearch-cluster-master -n default || echo "❌ No OpenSearch master pods found in default namespace"

# Check OpenSearch service
echo "🌐 OpenSearch services in default namespace:"
kubectl get svc -l app=opensearch-cluster-master -n default || echo "❌ No OpenSearch services found in default namespace"

# Test OpenSearch connectivity
echo "🔗 Testing OpenSearch connectivity..."
OPENSEARCH_POD=$(kubectl get pods -l app=opensearch-cluster-master -n default -o jsonpath="{.items[0].metadata.name}" 2>/dev/null || echo "")

if [ -n "$OPENSEARCH_POD" ]; then
    echo "📡 Testing connection from pod: $OPENSEARCH_POD"
    kubectl exec -n default $OPENSEARCH_POD -- curl -s -k "https://localhost:9200" || echo "❌ Cannot connect to OpenSearch"
else
    echo "❌ No OpenSearch pod found to test connectivity"
fi

# Check cluster health via port-forward (if possible)
echo "🏥 Attempting to check cluster health via port-forward..."
kubectl port-forward -n default svc/opensearch-cluster-master 9200:9200 &
PORT_FORWARD_PID=$!
sleep 2

curl -s "http://localhost:9200/_cluster/health?pretty" && echo "✅ OpenSearch cluster is accessible" || echo "❌ Cannot reach OpenSearch cluster"

# Clean up port-forward
kill $PORT_FORWARD_PID 2>/dev/null || true

echo "✅ OpenSearch verification complete"